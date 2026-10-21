"""업무 흐름: 공정런 저장(P1), 분기(P2), 시험런·탑승(P3), 결과 저장(P4), 실측 붙여넣기."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (ParamActual, ProcessPreset, ProcessRun, Project, RunSpecimen, Specimen, TestResult,
                      TestRun, TestTemplate)
from ..schemas import ProcessRunIn, SplitIn, TestRunIn
from . import actuals
from . import condition_code as cc
from . import numbering
from . import param_dict as pdict
from .templates_engine import validate_metrics


class Conflict(Exception):
    """번호 충돌 (409)."""

    def __init__(self, message: str, items: list[str]):
        super().__init__(message)
        self.items = items


class Invalid(ValueError):
    def __init__(self, message: str, items: list[str] | None = None):
        super().__init__(message)
        self.items = items or []


# ── P1. 공정런 → 원판 생성 ─────────────────────────────────────────
def series_overrides(payload: ProcessRunIn) -> list[dict]:
    """시리즈 설정 → 원판별 target_overrides (바뀐 키만, 6.9절)."""
    per_panel: list[dict] = [{} for _ in range(payload.panel_count)]
    series = payload.series_list()
    if len(series) > 2:
        raise Invalid("시리즈 키는 둘까지 조합할 수 있습니다.")
    for s in series:
        p = pdict.param(s.key)
        if p is None or not pdict.is_numeric(s.key):
            raise Invalid(f"시리즈 키가 사전에 없거나 숫자가 아닙니다: {s.key}")
        if len(s.values) != payload.panel_count:
            raise Invalid(f"시리즈 {s.key} 값 {len(s.values)}개 ≠ 원판 {payload.panel_count}매")
        base = pdict.get(payload.recipe, s.key)
        for i, v in enumerate(s.values):
            if "min" in p and not (p["min"] <= v <= p["max"]):
                raise Invalid(f"시리즈 {pdict.label(s.key)} {v:g} — 허용 범위 {p['min']}~{p['max']} 밖")
            if base is None or float(base) != float(v):
                per_panel[i][s.key] = v
    return per_panel


def create_process_run(db: Session, payload: ProcessRunIn, user_id: int | None) -> ProcessRun:
    if payload.dict_version != pdict.version():
        raise Invalid(f"파라미터 사전 버전이 다릅니다 (화면 {payload.dict_version}, 서버 {pdict.version()}). 새로고침하세요.")
    if db.get(Project, payload.project_code) is None:
        raise Invalid(f"과제코드 {payload.project_code}가 없습니다.")
    # 1. 기본값 위에 화면 레시피를 얹고, 사전 min/max로 범위 재검증 (브라우저 검증은 신뢰하지 않음)
    recipe = pdict.merge(pdict.defaults(), payload.recipe)
    recipe.setdefault("out", {})["cw"] = payload.coating_weight_target
    errs = pdict.out_of_range(recipe)
    if errs and not payload.confirm_out_of_range:
        raise Invalid("허용 범위 밖 값이 있습니다. 확인 후 다시 저장하세요.", errs)

    preset = db.get(ProcessPreset, payload.preset_id) if payload.preset_id else None
    sys_code = (preset.coating_system if preset else (payload.coating_system or "")).upper()[:1]
    if not sys_code:
        raise Invalid("도금 계열을 정할 수 없습니다. 프리셋을 고르거나 지난 공정런을 복제하세요.")

    # 2. 시리즈 → 원판별 목표 변경 → 원판마다 목표 기준 조건부
    overrides = series_overrides(payload)
    codes = cc.CodeBook.load(db)
    preferred = preset.bath_code if preset else None
    base_code = cc.code_from_recipe(codes, sys_code, recipe, preferred)

    # 3. 번호 충돌 검사
    clash = numbering.conflicts(db, payload.project_code, "P", payload.serial_start, payload.panel_count)
    if clash:
        raise Conflict("이미 쓰인 원판 번호가 있습니다.", clash)

    server_warn = [c["msg"] for c in pdict.checks(recipe, sys_code)]
    run = ProcessRun(run_no=numbering.next_run_no(db, payload.run_date), run_date=payload.run_date,
                     operator_id=user_id, project_code=payload.project_code, material_id=payload.material_id,
                     preset_id=preset.id if preset else None, source=payload.source, dict_version=pdict.version(),
                     recipe=recipe, changed_from_preset=payload.changed_from_preset,
                     coating_weight_target=payload.coating_weight_target, base_condition_code=base_code,
                     note=payload.note or None, warnings=server_warn or payload.warnings,
                     coating_system=sys_code)
    db.add(run)
    db.flush()
    # 4. 같은 트랜잭션에서 원판 N매 (과제·원소재·조건 상속)
    for i in range(payload.panel_count):
        ov = overrides[i] or None
        panel_rcp = pdict.merge(recipe, ov)
        code = cc.code_from_recipe(codes, sys_code, panel_rcp, preferred)
        serial = numbering.serial_str(payload.serial_start + i)
        sp = Specimen(project_code=payload.project_code, stage="P", serial_no=serial, process_run_id=run.id,
                      material_id=payload.material_id, owner_id=user_id, target_overrides=ov,
                      condition_code=code, size_text="200x300",
                      engraved_label=f"{code}-{payload.project_code}-P{serial}")
        db.add(sp)
    db.flush()
    actuals.recompute_run(db, run)
    return run


def clone_payload(run: ProcessRun) -> dict:
    """[지난 공정런 복제]: 레시피·계열·목표 부착량을 그대로 채움."""
    return {"run_no": run.run_no, "recipe": run.recipe, "preset_id": run.preset_id,
            "coating_system": run.coating_system, "coating_weight_target": run.coating_weight_target,
            "project_code": run.project_code, "material_id": run.material_id,
            "panel_count": len(run.panels)}


# ── P2. 분기 ─────────────────────────────────────────────────────
def split(db: Session, parent: Specimen, data: SplitIn, user_id: int | None) -> list[Specimen]:
    stage = data.stage.upper()
    allowed = {"P": ("C", "S"), "C": ("S",), "S": ()}[parent.stage]
    if stage not in allowed:
        raise Invalid(f"{parent.stage} 단계에서는 {', '.join(allowed) or '더 이상'} 분기할 수 없습니다.")
    clash = numbering.conflicts(db, parent.project_code, stage, data.serial_start, data.count)
    if clash:
        raise Conflict("이미 쓰인 번호가 있습니다.", clash)
    kids = []
    for i in range(data.count):
        serial = numbering.serial_str(data.serial_start + i)
        k = Specimen(project_code=parent.project_code, stage=stage, serial_no=serial, parent_id=parent.id,
                     process_run_id=parent.process_run_id, material_id=parent.material_id, owner_id=user_id,
                     condition_code=parent.condition_code,
                     sample_position=data.sample_position, rolling_direction=data.rolling_direction,
                     surface_side=data.surface_side,
                     size_text=data.size_text or ("70x150" if stage == "C" else "20x20"),
                     storage_location=data.storage_location)
        k.engraved_label = f"{parent.condition_code or 'XXXXX'}-{parent.project_code}-{stage}{serial}"
        db.add(k)
        kids.append(k)
    if data.mark_parent_consumed:
        parent.status = "CONSUMED"
    db.flush()
    if parent.process_run is not None:
        actuals.recompute_run(db, parent.process_run)
    return kids


# ── P3. 시험런 생성·탑승 ───────────────────────────────────────────
def find_specimen(db: Session, short_id: str) -> Specimen | None:
    return db.scalar(select(Specimen).where(Specimen.short_id == short_id.strip().upper(),
                                            Specimen.is_deleted.is_(False)))


def create_test_run(db: Session, data: TestRunIn, user_id: int | None) -> TestRun:
    tpl = db.get(TestTemplate, data.template_id)
    if tpl is None:
        raise Invalid("템플릿이 없습니다.")
    missing = [b.short_id for b in data.specimens if find_specimen(db, b.short_id) is None]
    if missing:
        raise Invalid("없는 시편이 있습니다.", missing)
    tr = TestRun(test_run_no=numbering.next_test_run_no(db, tpl.test_type, data.start_date),
                 test_type=tpl.test_type, template_id=tpl.id, equipment=data.equipment,
                 conditions=data.conditions, start_date=data.start_date, owner_id=user_id,
                 cycles=tpl.default_cycles or 1, note=data.note)
    db.add(tr)
    db.flush()
    for b in data.specimens:
        board(db, tr, find_specimen(db, b.short_id), b.slot, data.start_date)
    db.flush()
    return tr


def board(db: Session, tr: TestRun, spec: Specimen, slot: str | None, when: date | None = None) -> RunSpecimen:
    rs = db.get(RunSpecimen, (tr.id, spec.id))
    if rs is None:
        rs = RunSpecimen(test_run_id=tr.id, specimen_id=spec.id, slot=slot, loaded_at=when or date.today())
        db.add(rs)
        tr.boardings.append(rs)
    else:
        rs.slot = slot or rs.slot
        rs.unloaded_at = None
    spec.status = "IN_TEST"
    return rs


def unload(db: Session, tr: TestRun, spec: Specimen, when: date | None = None) -> None:
    rs = db.get(RunSpecimen, (tr.id, spec.id))
    if rs is not None and rs.unloaded_at is None:
        rs.unloaded_at = when or date.today()
        db.flush()
        still = db.scalar(select(RunSpecimen).where(RunSpecimen.specimen_id == spec.id,
                                                    RunSpecimen.test_run_id != tr.id,
                                                    RunSpecimen.unloaded_at.is_(None)))
        if still is None and spec.status == "IN_TEST":
            spec.status = "AVAILABLE"


def finish_test_run(db: Session, tr: TestRun, when: date | None = None) -> None:
    tr.status = "DONE"
    tr.end_date = when or date.today()
    for rs in tr.boardings:
        unload(db, tr, rs.specimen, tr.end_date)


# ── P4. 결과 저장 (+ maps_to 실측 연동, D-33) ───────────────────────
def save_result(db: Session, tr: TestRun, spec: Specimen, cycle_no: int, raw: dict, user_id: int | None,
                eval_date: date | None = None) -> tuple[TestResult, list[str]]:
    if not any(b.specimen_id == spec.id for b in tr.boardings):
        raise Invalid(f"{spec.short_id}은 {tr.test_run_no}에 탑승하지 않았습니다.")
    tpl = tr.template
    res = db.scalar(select(TestResult).where(TestResult.test_run_id == tr.id, TestResult.specimen_id == spec.id,
                                             TestResult.cycle_no == cycle_no))
    metrics, warnings = validate_metrics(tpl, raw)
    if res is None:
        res = TestResult(test_run_id=tr.id, specimen_id=spec.id, cycle_no=cycle_no, template_id=tpl.id,
                         inspector_id=user_id, eval_date=eval_date or date.today(), metrics=metrics)
        db.add(res)
    else:
        res.metrics = metrics
        res.is_deleted = False
        res.inspector_id = user_id
        if eval_date:
            res.eval_date = eval_date
    if (tr.cycles or 0) <= cycle_no:
        tr.cycles = cycle_no + 1
    db.flush()
    sync_mapped_actuals(db, res, user_id)
    return res, warnings


def sync_mapped_actuals(db: Session, res: TestResult, user_id: int | None) -> None:
    """템플릿 필드의 maps_to → 해당 시편의 실측 행 생성·갱신(출처 test)."""
    spec = res.specimen or db.get(Specimen, res.specimen_id)
    if spec.process_run is None:
        return
    tpl = res.template or db.get(TestTemplate, res.template_id)
    changed = False
    method = (res.metrics or {}).get("method")
    for f in tpl.field_schema:
        key = f.get("maps_to")
        if not key:
            continue
        rows = db.scalars(select(ParamActual).where(ParamActual.ref_result_id == res.id,
                                                    ParamActual.param_key == key,
                                                    ParamActual.is_deleted.is_(False))).all()
        val = (res.metrics or {}).get(f["key"])
        if val is None:
            for r in rows:
                r.is_deleted = True
                changed = True
            continue
        if rows:
            rows[0].value = float(val)
            rows[0].method = method
            for r in rows[1:]:
                r.is_deleted = True
        else:
            actuals.add_actual(db, spec.process_run, key, val, specimen=spec, source="test", method=method,
                               user_id=user_id, ref_result_id=res.id)
        changed = True
    if changed:
        actuals.recompute_run(db, spec.process_run)


# ── 엑셀 붙여넣기 ─────────────────────────────────────────────────
def split_table(text: str) -> list[list[str]]:
    rows = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            continue
        rows.append([c.strip() for c in (line.split("\t") if "\t" in line else re.split(r"\s{2,}|,", line))])
    return rows


SHORT_RE = re.compile(r"\d{2}[A-Z][0-9A-Z]-[PCS]\d{4}")


def parse_results_paste(db: Session, tr: TestRun, text: str) -> tuple[list[dict], list[str]]:
    """시험런 붙여넣기. 첫 행 머리글: 시편 | W00 | W01 … (grid 필드 값) 또는 시편 | 회차 | 필드키…"""
    rows = split_table(text)
    if not rows:
        return [], ["붙여넣은 내용이 없습니다."]
    head = [h.upper() for h in rows[0]]
    tpl = tr.template
    fields = {f["key"].upper(): f["key"] for f in tpl.field_schema}
    fields.update({f["label"].upper(): f["key"] for f in tpl.field_schema})
    grid_key = tpl.grid_fields[0]["key"] if tpl.grid_fields else None
    items, errors = [], []
    wide = all(re.fullmatch(r"[WC]\d{1,3}", h) for h in head[1:]) and len(head) > 1
    for r in rows[1:]:
        sid = (r[0] if r else "").upper()
        m = SHORT_RE.search(sid)
        if not m:
            errors.append(f"약식번호를 읽지 못한 행: {' | '.join(r)}")
            continue
        sid = m.group(0)
        if wide:
            for h, v in zip(head[1:], r[1:]):
                if v != "":
                    items.append({"short_id": sid, "cycle": int(h[1:]), "metrics": {grid_key: v}})
        else:
            cyc_i = next((i for i, h in enumerate(head) if h in ("회차", "CYCLE", "주기")), None)
            cyc = 0
            if cyc_i is not None and cyc_i < len(r):
                cyc = int(re.sub(r"\D", "", r[cyc_i]) or 0)
            met = {}
            for i, h in enumerate(head[1:], start=1):
                if i == cyc_i or i >= len(r):
                    continue
                key = fields.get(h, h.lower())
                met[key] = r[i]
            items.append({"short_id": sid, "cycle": cyc, "metrics": met})
    return items, errors


def parse_actuals_paste(run: ProcessRun, text: str) -> tuple[list[dict], list[str]]:
    """실측 탭 붙여넣기. 머리글: 원판 | pot.T | 최고 판온 … (키 또는 라벨). '세션' 행은 공통값."""
    rows = split_table(text)
    if not rows:
        return [], ["붙여넣은 내용이 없습니다."]
    keymap = {}
    for k, p in pdict.params().items():
        keymap[k.upper()] = k
        keymap[p["l"].upper()] = k
        keymap[f"{p['section_nm']} {p['l']}".upper()] = k
        for alias in p.get("aka", []):
            keymap[alias.upper()] = k
    head = rows[0]
    keys, errors = [], []
    for h in head[1:]:
        k = keymap.get(h.strip().upper()) or keymap.get(re.sub(r"\s*\(.*\)$", "", h.strip()).upper())
        if k is None:
            errors.append(f"사전에 없는 열 머리글: {h}")
        keys.append(k)
    items = []
    for r in rows[1:]:
        who = r[0].strip().upper() if r else ""
        m = SHORT_RE.search(who)
        sid = m.group(0) if m else (None if who in ("세션", "SESSION", "공통", "RUN") else "?")
        if sid == "?":
            errors.append(f"약식번호(또는 '세션')를 읽지 못한 행: {' | '.join(r)}")
            continue
        for k, v in zip(keys, r[1:]):
            if k and v not in ("", "·", "-"):
                items.append({"specimen": sid, "key": k, "value": v})
    return items, errors
