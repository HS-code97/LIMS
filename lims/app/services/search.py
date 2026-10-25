"""조건·과제·분석·수치 필터 검색 (5.1 #5, 6.7절 기준 토글, D-34)."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import EffectiveParam, Material, ProcessRun, RunSpecimen, Specimen, TestRun
from . import marking
from . import param_dict as pdict

BASIS = {"effective": "대표값(실측 우선)", "target": "목표 기준", "actual": "실측 있는 것만"}


@dataclass
class ParamFilter:
    key: str
    lo: float | None = None
    hi: float | None = None


@dataclass
class Query:
    q: str = ""
    project: str = ""
    stage: str = ""
    status: str = ""
    test_type: str = ""
    code: str = ""
    basis: str = "effective"
    params: list[ParamFilter] = field(default_factory=list)
    limit: int = 500


def parse_query(args) -> Query:
    """쿼리스트링(k1, lo1, hi1, k2 …) → Query."""
    qy = Query(q=args.get("q", "").strip(), project=args.get("project", "").strip().upper(),
               stage=args.get("stage", ""), status=args.get("status", ""), test_type=args.get("test_type", ""),
               code=args.get("code", "").strip().upper(), basis=args.get("basis", "effective"))
    if qy.basis not in BASIS:
        qy.basis = "effective"
    for i in range(1, 6):
        k = args.get(f"k{i}")
        if not k or pdict.param(k) is None:
            continue

        def num(v):
            try:
                return float(v) if v not in (None, "") else None
            except ValueError:
                return None
        qy.params.append(ParamFilter(k, num(args.get(f"lo{i}")), num(args.get(f"hi{i}"))))
    return qy


def code_filter(code: str) -> list:
    """조건 검색어 → 조건식.
    'M2-03'   조건 카드: 계열 M2의 변형 03 (부착량·소둔 등급 무관, 같은 공정)
    'M206K03' 꼬리 그대로: 조건부 M206K + 변형 03 ('M206K00' = 공용 표준만)
    'M206'    조건부 접두 (? = 한 글자, 변형번호 무관)"""
    m = marking.VARIANT_ID_RE.match(code)
    if m:
        return [Specimen.condition_code.like(m["family"] + "%"), Specimen.variant_seq == int(m["seq"])]
    plate = marking.parse_plate(code)
    if plate and plate[1] is not None and "?" not in code:
        return [Specimen.condition_code == plate[0], Specimen.variant_seq == plate[1]]
    return [Specimen.condition_code.like(code.replace("?", "_") + "%")]


def build(qy: Query):
    """검색 SELECT 문 (DB 방언과 무관하게 구성 — PostgreSQL 컴파일 검사에도 씀)."""
    stmt = select(Specimen).where(Specimen.is_deleted.is_(False))
    if qy.q:
        q = marking.find_mark(qy.q) or qy.q.upper()       # 전체번호를 넣으면 각인번호로
        like = f"%{q}%"
        plate = marking.parse_plate(q)                   # 'M206K03'처럼 변형번호까지 친 꼬리
        by_label = and_(*code_filter(q)) if plate and plate[1] is not None else Specimen.condition_code.like(like)
        stmt = stmt.outerjoin(Material, Material.id == Specimen.material_id) \
                   .outerjoin(ProcessRun, ProcessRun.id == Specimen.process_run_id) \
                   .where(or_(Specimen.short_id.like(like), Material.coil_no.like(like),
                              ProcessRun.run_no.like(like), by_label,
                              Specimen.legacy_id.like(like)))
    if qy.project:
        stmt = stmt.where(Specimen.project_code == qy.project)
    if qy.stage:
        stmt = stmt.where(Specimen.stage == qy.stage)
    if qy.status:
        stmt = stmt.where(Specimen.status == qy.status)
    if qy.code:
        stmt = stmt.where(*code_filter(qy.code))
    if qy.test_type:
        stmt = stmt.where(Specimen.id.in_(
            select(RunSpecimen.specimen_id).join(TestRun, TestRun.id == RunSpecimen.test_run_id)
            .where(TestRun.test_type == qy.test_type)))
    for f in qy.params:
        ep = aliased(EffectiveParam)
        col = {"effective": ep.effective, "target": ep.target, "actual": ep.actual}[qy.basis]
        conds = [ep.specimen_id == Specimen.id, ep.param_key == f.key, col.is_not(None)]
        if f.lo is not None:
            conds.append(col >= f.lo)
        if f.hi is not None:
            conds.append(col <= f.hi)
        stmt = stmt.join(ep, and_(*conds))
    return stmt.order_by(Specimen.short_id).limit(qy.limit)


def run(db: Session, qy: Query) -> list[Specimen]:
    return list(db.scalars(build(qy)).unique())


def effective_map(db: Session, spec_ids: list[int], keys: list[str]) -> dict[tuple[int, str], EffectiveParam]:
    if not spec_ids or not keys:
        return {}
    rows = db.scalars(select(EffectiveParam).where(EffectiveParam.specimen_id.in_(spec_ids),
                                                   EffectiveParam.param_key.in_(keys)))
    return {(r.specimen_id, r.param_key): r for r in rows}


def autocomplete(db: Session, q: str, limit: int = 10) -> list[dict]:
    """상단 검색창 자동완성: 각인번호·코일번호·공정런·분석런."""
    q = q.strip().upper()
    if not q:
        return []
    like = f"%{marking.find_mark(q) or q}%"
    out = []
    for s in db.scalars(select(Specimen).where(Specimen.short_id.like(like), Specimen.is_deleted.is_(False))
                        .order_by(Specimen.short_id).limit(limit)):
        out.append({"label": s.short_id, "sub": f"{s.display_id} · {s.stage_name}", "href": f"/specimens/{s.short_id}"})
    like = f"%{q}%"
    # 옛 분석런 번호(TR-…, 0005에서 AR-…로 바뀜)로 찾아도 됩니다.
    tr_like = f"%AR-{q[3:]}%" if q.startswith("TR-") else like
    for t in db.scalars(select(TestRun).where(TestRun.test_run_no.like(tr_like)).limit(5)):
        out.append({"label": t.test_run_no, "sub": f"분석런 · {t.equipment or ''}", "href": f"/test-runs/{t.test_run_no}"})
    for r in db.scalars(select(ProcessRun).where(ProcessRun.run_no.like(like)).limit(5)):
        out.append({"label": r.run_no, "sub": f"공정런 · {r.run_date}", "href": f"/process-runs/{r.run_no}"})
    for m in db.scalars(select(Material).where(or_(Material.coil_no.like(like), Material.coil_code == q)).limit(5)):
        href = f"/specimens?coil={m.coil_code}" if m.coil_code else f"/search?q={m.coil_no}"
        out.append({"label": m.coil_no, "sub": f"코일 · {m.label}", "href": href})
    return out[:limit + 5]
