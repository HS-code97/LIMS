"""실측 기록·대표값 산출·편차 (6.6~6.8절, D-29~D-36).

대표값 규칙(6.7절): 자신 → 부모 원판(→ 조부모) 순으로 실측을 찾고, 없으면 세션(공정런 공통) 실측,
그래도 없으면 목표값. 같은 노드에 여러 출처가 있으면 가장 최근에 잰 행의 출처를 고르고(D-37, 같은 시각이면
출처 순위 test > lab > manual > pv), 그 출처의 행들을 agg(mean/last/median)로 계산합니다.
결과는 effective_params 캐시에 저장합니다.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import SOURCE_PRIORITY
from ..errors import Invalid
from ..models import BathAnalysis, EffectiveParam, ParamActual, ProcessRun, Specimen
from . import condition_code as cc
from . import param_dict as pdict

SOURCE_LABEL = {"manual": "실측", "lab": "욕분석", "test": "분석", "pv": "PV", "target": "목표"}   # test = 분석런 결과, lab = 욕 시료 분석


@dataclass
class Effective:
    key: str
    target: float | None
    actual: float | None
    effective: float
    source: str
    level: str                       # target / run / 시편 단계(A~E)
    inherited_from: str | None = None
    deviation: float | None = None
    out_of_tol: bool = False
    is_override: bool = False        # 원판별 목표 변경(시리즈, 의도된 변화)

    @property
    def badge(self) -> str:
        return badge_text(self.source, self.level, self.inherited_from)

    @property
    def deviation_pct(self) -> float | None:
        if self.deviation is None or not self.target:
            return None
        return round(self.deviation / self.target * 100, 1)


def badge_text(source: str, level: str, inherited_from: str | None) -> str:
    if level == "target":
        return "목표"
    if level == "run":
        return "세션" if source == "manual" else f"세션·{SOURCE_LABEL.get(source, source)}"
    base = SOURCE_LABEL.get(source, source)
    if inherited_from:
        return f"{base}·{inherited_from.split('-', 1)[-1]}"
    return base


def _to_float(v):
    try:
        f = None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None
    return f if f is None or math.isfinite(f) else None


def _measured(v) -> float | None:
    """입력 실측값 → 숫자(숫자가 아니면 None = 텍스트 값). 'nan'·'inf'는 숫자처럼 보이지만 거부합니다."""
    try:
        f = None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None
    if f is not None and not math.isfinite(f):
        raise Invalid(f"숫자가 아닌 실측값입니다: {v!r}")
    return f


def _when(r: ParamActual) -> datetime:
    return r.measured_at or r.created_at or datetime.min


def aggregate(rows: list[ParamActual], key: str) -> tuple[float | None, str]:
    """가장 최근에 잰 행의 출처(같은 시각이면 출처 순위)를 고르고, 그 출처 행들로 agg 계산 (D-37).
    나중에 넣은 수기 정정이 앞선 분석 결과 값을 대신하게 됩니다."""
    rows = [r for r in rows if r.value is not None]
    if not rows:
        return None, ""
    rank = {s: i for i, s in enumerate(SOURCE_PRIORITY)}
    best = max(rows, key=lambda r: (_when(r), -rank.get(r.source, 99))).source
    grp = sorted([r for r in rows if r.source == best], key=lambda r: (_when(r), r.id or 0))
    agg = pdict.actual_cfg(key).get("agg", "mean")
    vals = [r.value for r in grp]
    if agg == "last":
        v = vals[-1]
    elif agg == "median":
        v = statistics.median(vals)
    else:
        v = statistics.fmean(vals)
    return round(v, 6), best


def tolerance_check(key: str, target: float | None, actual: float | None) -> tuple[float | None, bool]:
    if target is None or actual is None:
        return None, False
    dev = actual - target
    cfg = pdict.actual_cfg(key)
    if "tol" in cfg:
        return dev, abs(dev) > cfg["tol"] + 1e-9
    if "tol_pct" in cfg and target:
        return dev, abs(dev) / abs(target) * 100 > cfg["tol_pct"] + 1e-9
    return dev, False


def lineage_up(spec: Specimen) -> list[Specimen]:
    out, node = [], spec
    while node is not None:
        out.append(node)
        node = node.parent
    return out


class RunActuals:
    """공정런 하나의 실측 행을 한 번에 읽어 대표값을 계산합니다(시편·자손이 모두 같은 공정런)."""

    def __init__(self, db: Session, run: ProcessRun):
        self.db, self.run = db, run
        self.rows: dict[tuple[int | None, str], list[ParamActual]] = defaultdict(list)
        for r in db.scalars(select(ParamActual).where(ParamActual.process_run_id == run.id,
                                                      ParamActual.is_deleted.is_(False))):
            self.rows[(r.specimen_id, r.param_key)].append(r)

    def effective(self, spec: Specimen, key: str) -> Effective | None:
        rcp = cc.target_recipe(spec)
        target = _to_float(pdict.target_value(rcp, key))
        panel = cc.panel_of(spec)
        is_override = bool(panel and panel.target_overrides and
                           (key in panel.target_overrides or
                            (key in ("out.cw_top", "out.cw_bottom") and "out.cw" in panel.target_overrides)))
        for node in lineage_up(spec):
            rows = self.rows.get((node.id, key))
            if rows:
                val, src = aggregate(rows, key)
                if val is not None:
                    dev, oot = tolerance_check(key, target, val)
                    return Effective(key, target, val, val, src, node.stage,
                                     None if node is spec else node.short_id, dev, oot, is_override)
        rows = self.rows.get((None, key))
        if rows:
            val, src = aggregate(rows, key)
            if val is not None:
                dev, oot = tolerance_check(key, target, val)
                return Effective(key, target, val, val, src, "run", None, dev, oot, is_override)
        if target is None:
            return None
        return Effective(key, target, None, target, "target", "target", None, None, False, is_override)

    def all_for(self, spec: Specimen) -> dict[str, Effective]:
        out = {}
        for key in pdict.numeric_keys():
            e = self.effective(spec, key)
            if e is not None:
                out[key] = e
        return out


def recompute_run(db: Session, run: ProcessRun) -> None:
    """공정런의 모든 시편(원판·쿠폰·조각) 대표값 캐시를 다시 계산합니다."""
    db.flush()
    # PostgreSQL: 같은 공정런을 두 요청이 동시에 다시 계산하면 DELETE→INSERT가 엇갈려 PK 충돌이나
    # 상대의 실측이 빠진 캐시가 생기므로 공정런 행을 잠가 차례로 계산합니다(SQLite는 쓰기가 원래 직렬).
    db.execute(select(ProcessRun.id).where(ProcessRun.id == run.id).with_for_update())
    ra = RunActuals(db, run)
    specs = db.scalars(select(Specimen).where(Specimen.process_run_id == run.id)).all()
    if not specs:
        return
    db.execute(delete(EffectiveParam).where(EffectiveParam.specimen_id.in_([s.id for s in specs])))
    for s in specs:
        for e in ra.all_for(s).values():
            db.add(EffectiveParam(specimen_id=s.id, param_key=e.key, target=e.target, actual=e.actual,
                                  effective=e.effective, source=e.source, level=e.level,
                                  inherited_from=e.inherited_from, deviation=e.deviation,
                                  out_of_tol=e.out_of_tol))
    db.flush()


def recompute_for_specimen(db: Session, spec: Specimen) -> None:
    if spec.process_run is not None:
        recompute_run(db, spec.process_run)


def actual_condition_code(db: Session, spec: Specimen, codes: cc.CodeBook | None = None) -> str | None:
    """실측 기준 조건부 (화면 표시용, D-31). 실측이 전혀 없으면 None."""
    if spec.process_run is None:
        return None
    ra = RunActuals(db, spec.process_run)
    found = {"any": False}

    def lookup(s: Specimen, key: str):
        e = ra.effective(s, key)
        if e and e.actual is not None:
            found["any"] = True
            return e.actual
        return None

    code = cc.specimen_code(db, spec, "actual", lookup, codes)
    return code if found["any"] else None


def add_actual(db: Session, run: ProcessRun, key: str, value, *, specimen: Specimen | None = None,
               source: str = "manual", method: str | None = None, user_id: int | None = None,
               points: list[float] | None = None, measured_at: datetime | None = None,
               ref_result_id: int | None = None, ref_analysis_id: int | None = None,
               note: str | None = None, stats: dict | None = None) -> ParamActual:
    if pdict.param(key) is None:
        raise ValueError(f"파라미터 사전에 없는 키입니다: {key}")
    fv = _measured(value)
    if points:
        pts = [float(p) for p in points]
        stats = {"points": pts, "min": min(pts), "max": max(pts), "n": len(pts)}
        if fv is None:
            fv = statistics.fmean(pts)
    row = ParamActual(process_run_id=run.id, specimen_id=specimen.id if specimen else None, param_key=key,
                      value=fv, value_text=None if fv is not None else (str(value) if value is not None else None),
                      stats=stats, source=source, method=method, user_id=user_id, note=note,
                      measured_at=measured_at or datetime.now(), ref_result_id=ref_result_id,
                      ref_analysis_id=ref_analysis_id)
    db.add(row)
    return row


def set_manual_cell(db: Session, run: ProcessRun, key: str, value, *, specimen: Specimen | None,
                    user_id: int | None, method: str | None = None) -> None:
    """실측 탭 셀 저장: 같은 셀(시편·키)의 수기 값은 덮어쓰고, 빈칸이면 수기 값을 논리 삭제."""
    q = select(ParamActual).where(ParamActual.process_run_id == run.id, ParamActual.param_key == key,
                                  ParamActual.source == "manual", ParamActual.is_deleted.is_(False))
    q = q.where(ParamActual.specimen_id == specimen.id) if specimen else q.where(ParamActual.specimen_id.is_(None))
    existing = db.scalars(q).all()
    fv = _measured(value)
    if fv is None:
        for r in existing:
            r.is_deleted = True
        return
    if existing and len(existing) == 1 and not existing[0].stats:
        existing[0].value = fv
        existing[0].method = method or existing[0].method
        existing[0].measured_at = datetime.now()
        existing[0].user_id = user_id
        return
    for r in existing:
        r.is_deleted = True
    add_actual(db, run, key, fv, specimen=specimen, source="manual", method=method, user_id=user_id)


def bath_values(analysis: BathAnalysis) -> dict[str, float]:
    """욕 분석 조성 → 세션 실측 키. 'bal.'(잔부) 원소는 100 − 나머지 합으로 계산."""
    comp = analysis.composition or {}
    nums = {el: _to_float(v) for el, v in comp.items()}
    known = sum(v for v in nums.values() if v is not None)
    out = {}
    for el, v in comp.items():
        if f"pot.{el}" not in pdict.params():
            continue
        if isinstance(v, str) and v.strip().lower().startswith("bal"):
            out[f"pot.{el}"] = round(100 - known, 3)
        elif nums[el] is not None:
            out[f"pot.{el}"] = nums[el]
    # 사전에 있는 원소인데 분석표에 없으면 0으로 간주하지 않고 비워 둡니다.
    return out


def apply_bath_analysis(db: Session, analysis: BathAnalysis, runs: list[ProcessRun], user_id: int | None) -> int:
    n = 0
    vals = bath_values(analysis)
    for run in runs:
        # 같은 분석을 다시 적용하면 기존 행을 대체
        for r in db.scalars(select(ParamActual).where(ParamActual.process_run_id == run.id,
                                                      ParamActual.ref_analysis_id == analysis.id,
                                                      ParamActual.is_deleted.is_(False))):
            r.is_deleted = True
        for key, v in vals.items():
            add_actual(db, run, key, v, source="lab", method=analysis.method, user_id=user_id,
                       measured_at=analysis.sampled_at, ref_analysis_id=analysis.id)
            n += 1
        recompute_run(db, run)
    return n
