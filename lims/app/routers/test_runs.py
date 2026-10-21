"""시험런: 생성·탑승·결과 그리드·셀 입력·엑셀 붙여넣기 (5.4절, 7장 P3·P4)."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import ensure_can_edit, require_user
from ..db import get_db
from ..models import Attachment, TestResult, TestRun, TestTemplate, User
from ..schemas import Boarding, PasteIn, ResultIn, TestRunIn
from ..services import export, workflow
from ..services.templates_engine import MetricsError, cell_text, condition_defaults
from ..web import render

router = APIRouter()


def get_tr(db: Session, no: str) -> TestRun:
    tr = db.scalar(select(TestRun).where(TestRun.test_run_no == no))
    if tr is None:
        raise HTTPException(404, f"시험런 {no}이 없습니다.")
    return tr


def get_spec(db: Session, sid: str):
    s = workflow.find_specimen(db, sid)
    if s is None:
        raise HTTPException(404, f"시편 {sid}이 없습니다.")
    return s


@router.get("/test-runs")
def list_page(request: Request, status: str = "", mine: int = 0, test_type: str = "",
              user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = select(TestRun).order_by(TestRun.start_date.desc(), TestRun.id.desc())
    if status:
        q = q.where(TestRun.status == status)
    if mine:
        q = q.where(TestRun.owner_id == user.id)
    if test_type:
        q = q.where(TestRun.test_type == test_type)
    runs = db.scalars(q.limit(300)).all()
    types = sorted({t.test_type for t in db.scalars(select(TestTemplate))})
    return render(request, "test_runs.html", nav="tr", runs=runs, f=dict(status=status, mine=mine, test_type=test_type),
                  types=types)


@router.get("/test-runs/new")
def new_page(request: Request, specimens: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    tpls = db.scalars(select(TestTemplate).where(TestTemplate.is_active.is_(True))
                      .order_by(TestTemplate.test_type, TestTemplate.code, TestTemplate.version.desc())).all()
    latest = {}
    for t in tpls:
        latest.setdefault(t.code, t)
    tjson = [{"id": t.id, "code": t.code, "version": t.version, "name": t.name, "test_type": t.test_type,
              "condition_schema": t.condition_schema or [], "default_cycles": t.default_cycles,
              "defaults": condition_defaults(t), "team": t.team.name if t.team else ""} for t in latest.values()]
    pre = [s.strip().upper() for s in specimens.split(",") if s.strip()]
    return render(request, "test_run_new.html", nav="tr", templates_json=tjson, preset_specs=pre)


def grid_context(db: Session, tr: TestRun) -> dict:
    tpl = tr.template
    cycles = max(tr.cycles or tpl.default_cycles or 1, 1)
    results = {(r.specimen_id, r.cycle_no): r for r in db.scalars(
        select(TestResult).where(TestResult.test_run_id == tr.id, TestResult.is_deleted.is_(False)))}
    photos: dict[int, list[Attachment]] = {}
    if results:
        for a in db.scalars(select(Attachment).where(Attachment.result_id.in_([r.id for r in results.values()]),
                                                     Attachment.is_deleted.is_(False)).order_by(Attachment.id)):
            photos.setdefault(a.result_id, []).append(a)
    rows = sorted(tr.boardings, key=lambda b: ((b.slot or "~"), b.specimen.short_id))
    cells = {}
    for (sid, c), r in results.items():
        gv = [(r.metrics or {}).get(f["key"]) for f in tpl.grid_fields]
        hot = any(isinstance(v, (int, float)) and v > 0 for v in gv) and any("rust" in f["key"] for f in tpl.grid_fields)
        cells[(sid, c)] = {"r": r, "text": cell_text(tpl, r.metrics), "photos": photos.get(r.id, []), "hot": hot}
    cols = []
    for c in range(cycles):
        d = tr.start_date + timedelta(days=(tpl.default_interval_days or 0) * c) if tpl.default_interval_days else None
        cols.append({"n": c, "label": f"W{c:02d}" if (tpl.default_cycles or 1) > 1 or cycles > 1 else "결과",
                     "day": f"D+{(tpl.default_interval_days or 0) * c}" if tpl.default_interval_days else "",
                     "date": d})
    empty = sum(1 for b in rows if b.unloaded_at is None for c in range(cycles) if (b.specimen_id, c) not in cells)
    return {"tr": tr, "tpl": tpl, "rows": rows, "cols": cols, "cells": cells, "empty": empty}


@router.get("/test-runs/{no}")
def detail_page(request: Request, no: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    return render(request, "test_run_detail.html", nav="tr", **grid_context(db, tr))


@router.get("/test-runs/{no}/cell/{sid}/{cycle}")
def cell_fragment(request: Request, no: str, sid: str, cycle: int, user: User = Depends(require_user),
                  db: Session = Depends(get_db)):
    """셀 클릭 → 템플릿 필드로 만든 작은 폼 (HTMX 조각)."""
    tr = get_tr(db, no)
    spec = get_spec(db, sid)
    res = db.scalar(select(TestResult).where(TestResult.test_run_id == tr.id, TestResult.specimen_id == spec.id,
                                             TestResult.cycle_no == cycle))
    photos = db.scalars(select(Attachment).where(Attachment.result_id == res.id, Attachment.is_deleted.is_(False))
                        ).all() if res else []
    tpl = res.template if res else tr.template
    day = (tpl.default_interval_days or 0) * cycle if tpl.default_interval_days else None
    when = tr.start_date + timedelta(days=day) if day is not None else None
    slot = next((b.slot for b in tr.boardings if b.specimen_id == spec.id), None)
    # 앞·뒷면: 파일명 태그(_front/_back) 우선, 없으면 올린 순서
    pics, rest = {}, list(photos)
    for side in ("front", "back"):
        hit = next((a for a in rest if f"_{side}" in a.original_name.lower()), None)
        if hit:
            pics[side] = hit
            rest.remove(hit)
    for side in ("front", "back"):
        if side not in pics and rest:
            pics[side] = rest.pop(0)
    return render(request, "partials/cell_editor.html", tr=tr, tpl=tpl, spec=spec, cycle=cycle, res=res, photos=photos,
                  pics=pics, day=day, when=when, slot=slot)


# ── API ──────────────────────────────────────────────────────────
def tr_json(tr: TestRun) -> dict:
    return {"test_run_no": tr.test_run_no, "test_type": tr.test_type, "template": f"{tr.template.code} v{tr.template.version}",
            "equipment": tr.equipment, "conditions": tr.conditions, "start_date": tr.start_date.isoformat(),
            "status": tr.status, "cycles": tr.cycles,
            "specimens": [{"short_id": b.specimen.short_id, "slot": b.slot,
                           "loaded_at": b.loaded_at.isoformat() if b.loaded_at else None,
                           "unloaded_at": b.unloaded_at.isoformat() if b.unloaded_at else None} for b in tr.boardings]}


@router.post("/api/test-runs")
def create(data: TestRunIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = workflow.create_test_run(db, data, user.id)
    db.commit()
    return tr_json(tr)


@router.get("/api/test-runs/{no}")
def get_api(no: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return tr_json(get_tr(db, no))


@router.post("/api/test-runs/{no}/board")
def board(no: str, data: list[Boarding], user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    missing = [b.short_id for b in data if workflow.find_specimen(db, b.short_id) is None]
    if missing:
        raise HTTPException(422, "없는 시편: " + ", ".join(missing))
    for b in data:
        workflow.board(db, tr, get_spec(db, b.short_id), b.slot)
    db.commit()
    return tr_json(tr)


class UnloadIn(BaseModel):
    short_id: str
    when: date | None = None


@router.post("/api/test-runs/{no}/unload")
def unload(no: str, data: UnloadIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    workflow.unload(db, tr, get_spec(db, data.short_id), data.when)
    db.commit()
    return tr_json(tr)


@router.post("/api/test-runs/{no}/finish")
def finish(no: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    ensure_can_edit(user, tr.owner_id)
    workflow.finish_test_run(db, tr)
    db.commit()
    return tr_json(tr)


class CyclesIn(BaseModel):
    delta: int = 1


@router.post("/api/test-runs/{no}/cycles")
def change_cycles(no: str, data: CyclesIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """[+열] / 마지막 빈 열 삭제. 결과가 있는 열은 지우지 않습니다."""
    tr = get_tr(db, no)
    cur = tr.cycles or tr.template.default_cycles or 1
    new = max(1, cur + data.delta)
    if new < cur:
        used = db.scalar(select(TestResult.id).where(TestResult.test_run_id == tr.id, TestResult.cycle_no >= new,
                                                     TestResult.is_deleted.is_(False)))
        if used:
            raise HTTPException(409, "결과가 있는 회차 열은 지울 수 없습니다.")
    tr.cycles = new
    db.commit()
    return {"cycles": new}


@router.put("/api/test-runs/{no}/results/{sid}/{cycle}")
def put_result(no: str, sid: str, cycle: int, data: ResultIn, user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    spec = get_spec(db, sid)
    try:
        res, warnings = workflow.save_result(db, tr, spec, cycle, data.metrics, user.id, data.eval_date)
    except MetricsError as e:
        raise HTTPException(422, {"errors": e.errors})
    db.commit()
    return {"id": res.id, "metrics": res.metrics, "text": cell_text(tr.template, res.metrics), "warnings": warnings}


@router.post("/api/test-runs/{no}/paste")
def paste(no: str, data: PasteIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    items, errors = workflow.parse_results_paste(db, tr, data.text)
    boarded = {b.specimen.short_id for b in tr.boardings}
    for it in items:
        if it["short_id"] not in boarded:
            errors.append(f"{it['short_id']}은 이 시험런에 탑승하지 않았습니다.")
    warnings: list[str] = []
    if not errors:
        try:
            for it in items:
                spec = get_spec(db, it["short_id"])
                res = db.scalar(select(TestResult).where(TestResult.test_run_id == tr.id,
                                                         TestResult.specimen_id == spec.id,
                                                         TestResult.cycle_no == it["cycle"]))
                merged = dict(res.metrics or {}) if res else {}
                merged.update(it["metrics"])
                _, w = workflow.save_result(db, tr, spec, it["cycle"], merged, user.id)
                warnings += w
        except MetricsError as e:
            db.rollback()
            errors += e.errors
    if data.dry_run or errors:
        db.rollback()
        return {"items": items, "errors": errors, "warnings": warnings, "saved": 0}
    db.commit()
    return {"items": items, "errors": [], "warnings": sorted(set(warnings)), "saved": len(items)}


@router.get("/api/test-runs/{no}/export.xlsx")
def export_xlsx(request: Request, no: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = get_tr(db, no)
    data = export.test_run_xlsx(db, tr, str(request.base_url).rstrip("/"))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{tr.test_run_no}.xlsx"'})
