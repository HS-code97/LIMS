"""공정런 등록(HMI 기록 모드)·상세·실측 탭, 욕 분석 (5.2·5.3절, 6장)."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import ensure_can_edit, require_user
from ..db import get_db
from ..models import BathAnalysis, Material, ParamActual, ProcessRun, Project, Specimen, User
from ..schemas import ActualsIn, ApplyIn, BathAnalysisIn, PasteIn, ProcessRunIn, TargetCorrectionIn
from ..services import actuals, workflow
from ..services import param_dict as pdict
from ..services.condition_code import CodeBook
from ..web import render
from .presets import preset_json, visible_presets

router = APIRouter()


def get_run(db: Session, run_no: str) -> ProcessRun:
    run = db.scalar(select(ProcessRun).where(ProcessRun.run_no == run_no))
    if run is None:
        raise HTTPException(404, f"공정런 {run_no}이 없습니다.")
    return run


def run_specimens(db: Session, run: ProcessRun) -> list[Specimen]:
    return db.scalars(select(Specimen).where(Specimen.process_run_id == run.id, Specimen.is_deleted.is_(False))
                      .order_by(Specimen.short_id)).all()


# ── 화면 ─────────────────────────────────────────────────────────
@router.get("/process-runs")
def list_page(request: Request, project: str = "", mine: int = 0, user: User = Depends(require_user),
              db: Session = Depends(get_db)):
    q = select(ProcessRun).order_by(ProcessRun.run_date.desc(), ProcessRun.id.desc())
    if project:
        q = q.where(ProcessRun.project_code == project.upper())
    if mine:
        q = q.where(ProcessRun.operator_id == user.id)
    runs = db.scalars(q.limit(300)).all()
    projects = db.scalars(select(Project).order_by(Project.project_code.desc())).all()
    return render(request, "process_runs.html", nav="pr", runs=runs, projects=projects, project=project, mine=mine)


@router.get("/process-runs/new")
def new_page(request: Request, clone: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.is_common, Project.project_code.desc())).all()
    materials = db.scalars(select(Material).order_by(Material.received_date.desc().nulls_last(), Material.id.desc())).all()
    recent = db.scalars(select(ProcessRun).where(ProcessRun.operator_id == user.id)
                        .order_by(ProcessRun.created_at.desc(), ProcessRun.id.desc()).limit(10)).all()
    clone_data = workflow.clone_payload(get_run(db, clone)) if clone else None
    return render(request, "process_run_new.html", nav="pr", projects=projects, materials=materials,
                  presets=[preset_json(p) for p in visible_presets(db, user)],
                  recent=[workflow.clone_payload(r) | {"run_date": r.run_date.isoformat(),
                                                        "code": r.base_condition_code} for r in recent],
                  clone=clone_data, dictionary=pdict.load())


@router.get("/process-runs/{run_no}")
def detail_page(request: Request, run_no: str, tab: str = "panels", add: str = "", user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    run = get_run(db, run_no)
    extra = [k for k in add.split(",") if pdict.param(k) and pdict.is_numeric(k)]
    ctx = actuals_context(db, run, extra)
    near = db.scalars(select(BathAnalysis).where(
        BathAnalysis.sampled_at >= run.run_date - timedelta(days=1),
        BathAnalysis.sampled_at < run.run_date + timedelta(days=2)).order_by(BathAnalysis.sampled_at.desc())).all()
    all_ba = db.scalars(select(BathAnalysis).order_by(BathAnalysis.sampled_at.desc()).limit(30)).all()
    applied = {r.ref_analysis_id for r in db.scalars(select(ParamActual).where(
        ParamActual.process_run_id == run.id, ParamActual.ref_analysis_id.is_not(None),
        ParamActual.is_deleted.is_(False)))}
    return render(request, "process_run_detail.html", nav="pr", run=run, tab=tab, specs=run_specimens(db, run),
                  checks=pdict.checks(run.recipe, run.coating_system), near_ba=near, all_ba=all_ba,
                  applied_ba=applied, add=",".join(extra), **ctx)


def actuals_context(db: Session, run: ProcessRun, extra_keys: list[str] | None = None) -> dict:
    """실측 탭 표: 세션 공통 키 + 원판 수준 키(quick), 원판별 대표값."""
    ra = actuals.RunActuals(db, run)
    quick = pdict.quick_keys() + [k for k in (extra_keys or []) if k not in pdict.quick_keys()]
    if run.recipe.get("ga", {}).get("on") and "out.fe_pct" not in quick:
        quick.append("out.fe_pct")
    session_keys = [k for k in quick if pdict.actual_cfg(k)["level"] == "run"]
    panel_keys = [k for k in quick if k not in session_keys]
    panels = run.panels
    session_vals = {}
    for k in session_keys:
        rows = ra.rows.get((None, k), [])
        man = [r for r in rows if r.source == "manual"]
        val, src = actuals.aggregate(rows, k)
        tgt = pdict.target_value(run.recipe, k)
        dev, oot = actuals.tolerance_check(k, tgt, val)
        session_vals[k] = {"value": val, "source": src, "manual": man[-1].value if man else None,
                           "method": man[-1].method if man else None, "target": tgt, "oot": oot, "dev": dev,
                           "has_other": any(r.source != "manual" for r in rows)}
    cells = {}
    for p in panels:
        for k in panel_keys:
            e = ra.effective(p, k)
            rows = ra.rows.get((p.id, k), [])
            man = [r for r in rows if r.source == "manual"]
            cells[(p.id, k)] = {"eff": e, "manual": man[-1].value if man else None,
                                "auto": any(r.source in ("test", "pv", "lab") for r in rows),
                                "direct": bool(rows)}
    # 시험 결과에서 자동 채워질 칸 표시용: 템플릿 maps_to
    from ..models import TestTemplate
    maps = {}
    for t in db.scalars(select(TestTemplate).where(TestTemplate.is_active.is_(True))):
        for f in t.field_schema:
            if f.get("maps_to"):
                maps.setdefault(f["maps_to"], t.code)
    # 욕 조성: 목표 vs 욕 분석(출처 lab) 실측 — 5.3절 세션 공통 둘째 줄
    bath = []
    for el in ("Al", "Si", "Mg"):
        k = f"pot.{el}"
        rows = [r for r in ra.rows.get((None, k), []) if r.value is not None]
        val, src = actuals.aggregate(rows, k)
        last = max(rows, key=lambda r: r.measured_at or r.created_at) if rows else None
        dev, oot = actuals.tolerance_check(k, pdict.get(run.recipe, k), val)
        bath.append({"el": el, "target": pdict.get(run.recipe, k), "value": val, "source": src, "oot": oot,
                     "method": last.method if last else None, "at": last.measured_at if last else None})
    return {"session_keys": session_keys, "panel_keys": panel_keys, "panels": panels, "bath": bath,
            "session_vals": session_vals, "cells": cells, "maps": maps,
            "all_keys": [k for k in pdict.numeric_keys() if k not in quick and k != "out.cw"]}


# ── API ──────────────────────────────────────────────────────────
@router.get("/api/param-dictionary")
def param_dictionary():
    return pdict.load()


@router.post("/api/process-runs")
def create_run(data: ProcessRunIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    run = workflow.create_process_run(db, data, user.id)
    db.commit()
    return run_json(db, run)


@router.post("/api/process-runs/{run_no}/targets")
def correct_targets(run_no: str, data: TargetCorrectionIn, user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    """저장한 목표값 정정 (작성자·관리자). 전체번호 꼬리의 조건부를 다시 만듭니다(각인번호는 그대로)."""
    run = get_run(db, run_no)
    ensure_can_edit(user, run.operator_id)
    out = workflow.correct_targets(db, run, data.changes, data.reason, user.name, data.confirm_out_of_range)
    db.commit()
    return out | {"run": run_json(db, run)}


@router.post("/api/process-runs/preview-code")
def preview_code(payload: dict, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """조건부 미리보기 (화면 하단 'M206K → …')."""
    from ..services.condition_code import code_from_recipe
    from ..models import ProcessPreset
    recipe = pdict.merge(pdict.defaults(), payload.get("recipe") or {})
    recipe.setdefault("out", {})["cw"] = payload.get("coating_weight_target") or pdict.get(recipe, "out.cw")
    preset = db.get(ProcessPreset, payload["preset_id"]) if payload.get("preset_id") else None
    sys_code = preset.coating_system if preset else (payload.get("coating_system") or "X")
    codes = CodeBook.load(db)
    base = code_from_recipe(codes, sys_code, recipe, preset.bath_code if preset else None)
    per_panel = []
    for ov in payload.get("panel_overrides") or []:
        per_panel.append(code_from_recipe(codes, sys_code, pdict.merge(recipe, ov), preset.bath_code if preset else None))
    return {"code": base, "panel_codes": per_panel, "out_of_range": pdict.out_of_range(recipe),
            "checks": pdict.checks(recipe, sys_code)}


def run_json(db: Session, run: ProcessRun) -> dict:
    return {"run_no": run.run_no, "run_date": run.run_date.isoformat(), "project_code": run.project_code,
            "base_condition_code": run.base_condition_code, "recipe": run.recipe, "dict_version": run.dict_version,
            "coating_weight_target": run.coating_weight_target, "warnings": run.warnings,
            "panels": [{"short_id": p.short_id, "display_id": p.display_id, "condition_code": p.condition_code,
                        "target_overrides": p.target_overrides} for p in run.panels],
            "engrave_csv": f"/api/labels/engrave.csv?run={run.run_no}",
            "label_pdf": f"/api/labels/print.pdf?run={run.run_no}"}


@router.get("/api/process-runs/recent")
def recent_runs(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rs = db.scalars(select(ProcessRun).where(ProcessRun.operator_id == user.id)
                    .order_by(ProcessRun.created_at.desc(), ProcessRun.id.desc()).limit(10)).all()
    return [workflow.clone_payload(r) | {"run_date": r.run_date.isoformat(), "code": r.base_condition_code} for r in rs]


@router.get("/api/process-runs/{run_no}")
def get_run_api(run_no: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    run = get_run(db, run_no)
    out = run_json(db, run)
    ra = actuals.RunActuals(db, run)
    out["params"] = {p.short_id: {k: e.__dict__ | {"badge": e.badge} for k, e in ra.all_for(p).items()}
                     for p in run.panels}
    return out


def _check_actual_edit(user: User, run: ProcessRun, specs: list[Specimen]) -> None:
    ensure_can_edit(user, run.operator_id, *[s.owner_id for s in specs])


@router.post("/api/process-runs/{run_no}/actuals")
def post_actuals(run_no: str, data: ActualsIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    run = get_run(db, run_no)
    if data.source not in ("manual", "pv"):
        raise HTTPException(422, "이 경로의 출처는 manual 또는 pv입니다 (분석은 욕 분석 적용, 시험은 결과 저장).")
    specs = {s.short_id: s for s in run_specimens(db, run)}
    _check_actual_edit(user, run, [])
    n = 0
    for row in data.rows:
        spec = None
        if row.specimen:
            spec = specs.get(row.specimen.upper())
            if spec is None:
                raise HTTPException(422, f"{row.specimen}은 {run_no}의 시편이 아닙니다.")
        if pdict.param(row.key) is None:
            raise HTTPException(422, f"사전에 없는 키: {row.key}")
        if row.mode == "set" and data.source == "manual":
            actuals.set_manual_cell(db, run, row.key, row.value, specimen=spec, user_id=user.id, method=row.method)
        else:
            actuals.add_actual(db, run, row.key, row.value, specimen=spec, source=data.source, method=row.method,
                               user_id=user.id, points=row.points, measured_at=row.measured_at, note=row.note)
        n += 1
    actuals.recompute_run(db, run)
    db.commit()
    return {"saved": n}


@router.post("/api/process-runs/{run_no}/actuals/paste")
def paste_actuals(run_no: str, data: PasteIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    run = get_run(db, run_no)
    items, errors = workflow.parse_actuals_paste(run, data.text)
    specs = {s.short_id: s for s in run_specimens(db, run)}
    for it in items:
        if it["specimen"] and it["specimen"] not in specs:
            errors.append(f"{it['specimen']}은 이 공정런의 시편이 아닙니다.")
    if data.dry_run or errors:
        return {"items": items, "errors": errors, "saved": 0}
    _check_actual_edit(user, run, [])
    for it in items:
        actuals.set_manual_cell(db, run, it["key"], it["value"], specimen=specs.get(it["specimen"]) if it["specimen"] else None,
                                user_id=user.id)
    actuals.recompute_run(db, run)
    db.commit()
    return {"items": items, "errors": [], "saved": len(items)}


@router.post("/api/bath-analyses")
def create_bath_analysis(data: BathAnalysisIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ba = BathAnalysis(pot=data.pot, sampled_at=data.sampled_at, method=data.method, composition=data.composition,
                      user_id=user.id, note=data.note)
    db.add(ba)
    db.commit()
    return {"id": ba.id, "values": actuals.bath_values(ba), "candidates": bath_candidates(db, ba)}


def bath_candidates(db: Session, ba: BathAnalysis) -> list[dict]:
    """기본 제안: 시료 채취 시각 ±1일 공정런 (같은 포트 정보가 공정런에 없으므로 날짜로 제안)."""
    lo, hi = (ba.sampled_at - timedelta(days=1)).date(), (ba.sampled_at + timedelta(days=1)).date()
    rs = db.scalars(select(ProcessRun).where(ProcessRun.run_date >= lo, ProcessRun.run_date <= hi)
                    .order_by(ProcessRun.run_date)).all()
    return [{"run_no": r.run_no, "run_date": r.run_date.isoformat(), "code": r.base_condition_code} for r in rs]


@router.get("/api/bath-analyses/{ba_id}/candidates")
def get_candidates(ba_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ba = db.get(BathAnalysis, ba_id)
    if ba is None:
        raise HTTPException(404)
    return bath_candidates(db, ba)


@router.post("/api/bath-analyses/{ba_id}/apply")
def apply_bath(ba_id: int, data: ApplyIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ba = db.get(BathAnalysis, ba_id)
    if ba is None:
        raise HTTPException(404)
    runs = [get_run(db, no) for no in data.run_nos]
    for run in runs:                             # 욕 분석 적용은 각 공정런 작성자·관리자
        ensure_can_edit(user, run.operator_id)
    n = actuals.apply_bath_analysis(db, ba, runs, user.id)
    db.commit()
    return {"applied_rows": n, "runs": [r.run_no for r in runs]}
