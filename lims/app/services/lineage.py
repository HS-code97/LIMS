"""계보 조회 (7장 P6, 시편번호 체계 3.6절). 재귀 CTE는 PostgreSQL·SQLite 모두 지원합니다.

계보 = 자른 관계(부모 → 자식, 새 레코드). 도금·열처리·전처리·도장은 같은 레코드의 이력(steps·이벤트)입니다."""
from __future__ import annotations

from sqlalchemy import literal, select
from sqlalchemy.orm import Session, aliased

from ..models import Specimen
from .marking import TREATMENTS


def ancestors(spec: Specimen) -> list[Specimen]:
    """루트(전폭시편) → … → 부모 순서 (자신 제외)."""
    out, node = [], spec.parent
    while node is not None:
        out.append(node)
        node = node.parent
    return list(reversed(out))


def descendants_stmt(spec_id: int):
    """자손 재귀 CTE (7장 P6)."""
    base = select(Specimen.id, literal(0).label("depth")).where(Specimen.id == spec_id).cte("down", recursive=True)
    s = aliased(Specimen)
    cte = base.union_all(select(s.id, (base.c.depth + 1).label("depth")).where(s.parent_id == base.c.id))
    return select(cte.c.id, cte.c.depth).where(cte.c.depth > 0).order_by(cte.c.depth)


def descendant_ids(db: Session, spec_id: int) -> list[tuple[int, int]]:
    """(id, depth) 목록. 자신 제외."""
    rows = db.execute(descendants_stmt(spec_id)).all()
    return [(r[0], r[1]) for r in rows]


def descendants_tree(spec: Specimen) -> list[dict]:
    """[{spec, children:[...]}] 트리 (논리 삭제 제외)."""
    return [{"spec": c, "children": descendants_tree(c)} for c in spec.children if not c.is_deleted]


def processes(spec: Specimen) -> list[dict]:
    """실제로 거친 공정 ✓/– (단계 문자는 '현재 상태 등급'일 뿐 앞 단계를 다 거쳤다는 뜻이 아님, 3.4절)."""
    cut = spec.parent is not None or len(spec.branch or "") > 1
    out = [{"k": "CUT", "name": "전단", "done": cut, "codes": []}]
    for k, t in TREATMENTS.items():
        steps = [s for s in spec.steps or [] if s.get("k") == k]
        codes = [(spec.condition_label or "") if k == "PLATE" else f"{t['prefix']}{s.get('code', '')}" for s in steps]
        out.append({"k": k, "name": t["name"], "done": bool(steps), "codes": codes})
    return out


def chain(spec: Specimen) -> list[dict]:
    """계보 타임라인: 원소재(코일) → 전폭시편 → … → 자신. 도금한 시편 앞에 공정런을 끼워 보여 줍니다."""
    nodes: list[dict] = []
    if spec.material:
        nodes.append({"kind": "material", "label": spec.material.coil_no,
                      "sub": f"코일 {spec.material.coil_code}" if spec.material.coil_code else "원소재",
                      "href": f"/specimens?coil={spec.material.coil_code}" if spec.material.coil_code else None})
    run_shown = False
    for node in [*ancestors(spec), spec]:
        if node.is_panel and node.process_run and not run_shown:
            r = node.process_run
            nodes.append({"kind": "run", "label": r.run_no, "sub": f"도금 {r.run_date:%Y-%m-%d}",
                          "href": f"/process-runs/{r.run_no}"})
            run_shown = True
        nodes.append({"kind": "self" if node is spec else "specimen", "label": node.short_id,
                      "sub": f"{node.stage} {node.stage_name}"
                             + ("" if node.kind_name == node.stage_name else f" · {node.kind_name}"),
                      "href": f"/specimens/{node.short_id}"})
    return nodes
