"""3단계: 목표–실측 산점도, 좌우 동기화 사진 뷰어, PV 실행기록 수신, PPT, X-cut 블리스터 앱 연동."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import ensure_can_edit, require_user
from ..config import TMP_DIR
from ..db import get_db
from ..models import (Attachment, EffectiveParam, ParamActual, ProcessRun, Project, Specimen, TestResult, TestRun,
                      TestTemplate, User)
from ..services import actuals, file_ingest, ppt, pv, workflow
from ..services import param_dict as pdict
from ..services.templates_engine import MetricsError, cell_text
from ..web import render

router = APIRouter()
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


# ── 목표–실측 산점도 ────────────────────────────────────────────────
@router.get("/analysis/scatter")
def scatter_page(request: Request, key: str = "out.cw_top", project: str = "", user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    if pdict.param(key) is None:
        key = "out.cw_top"
    q = select(EffectiveParam, Specimen).join(Specimen, Specimen.id == EffectiveParam.specimen_id).where(
        EffectiveParam.param_key == key, EffectiveParam.actual.is_not(None), EffectiveParam.target.is_not(None),
        EffectiveParam.inherited_from.is_(None), Specimen.is_deleted.is_(False))
    if project:
        q = q.where(Specimen.project_code == project.upper())
    pts = [{"sid": s.short_id, "x": e.target, "y": e.actual, "dev": e.deviation, "oot": e.out_of_tol,
            "code": s.condition_code, "level": e.level, "badge": e.badge if hasattr(e, "badge") else
            actuals.badge_text(e.source, e.level, e.inherited_from)} for e, s in db.execute(q)]
    p = pdict.param(key)
    cfg = pdict.actual_cfg(key)
    keys = [(k, f"{pp['section_nm']} {pp['l']} ({pp['u']})") for k, pp in pdict.params().items()
            if pdict.is_numeric(k) and pp.get("actual")]
    projects = db.scalars(select(Project).order_by(Project.project_code.desc())).all()
    return render(request, "scatter.html", nav="search", key=key, p=p, cfg=cfg, pts=pts, keys=keys,
                  projects=projects, project=project)


# ── 좌우 동기화 사진 뷰어 ────────────────────────────────────────────
def _photos_by_cycle(db: Session, spec: Specimen) -> dict:
    out: dict = {}
    rows = db.execute(select(Attachment, TestResult, TestRun).join(TestResult, TestResult.id == Attachment.result_id)
                      .join(TestRun, TestRun.id == TestResult.test_run_id)
                      .where(Attachment.specimen_id == spec.id, Attachment.is_deleted.is_(False),
                             Attachment.thumb_path.is_not(None)).order_by(Attachment.id)).all()
    for a, r, tr in rows:
        out.setdefault(tr.test_run_no, {}).setdefault(r.cycle_no, {"photos": [], "text": cell_text(tr.template, r.metrics)})
        out[tr.test_run_no][r.cycle_no]["photos"].append({"id": a.id, "name": a.original_name})
    return out


@router.get("/viewer")
def viewer(request: Request, a: str = "", b: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    sa = workflow.find_specimen(db, a) if a else None
    sb = workflow.find_specimen(db, b) if b else None
    data = {}
    for s in (sa, sb):
        if s:
            data[s.short_id] = {"display": s.display_id, "runs": _photos_by_cycle(db, s)}
    return render(request, "viewer.html", nav="search", a=a.upper(), b=b.upper(), data=data)


# ── PV 실행기록 수신 (6.5절) ────────────────────────────────────────
@router.post("/api/process-runs/{run_no}/pv")
async def receive_pv(run_no: str, file: UploadFile = File(...), specimen: str = Form(""),
                     user: User = Depends(require_user), db: Session = Depends(get_db)):
    """HMI → PV 시계열 CSV (원판 1매 사이클 종료 시). specimen 비우면 세션 공통."""
    run = db.scalar(select(ProcessRun).where(ProcessRun.run_no == run_no))
    if run is None:
        raise HTTPException(404, f"공정런 {run_no}이 없습니다.")
    spec = None
    if specimen:
        spec = workflow.find_specimen(db, specimen)
        if spec is None or spec.process_run_id != run.id:
            raise HTTPException(422, f"{specimen}은 {run_no}의 시편이 아닙니다.")
    raw = await file.read()
    summary, warns = pv.summarize(raw.decode("utf-8", errors="replace"))
    if not summary:
        raise HTTPException(422, {"errors": warns or ["사전 pv_tag와 맞는 열이 없습니다."]})
    for key, st in summary.items():
        level = pdict.actual_cfg(key)["level"]
        target = spec if (spec is not None and level != "run") else None
        # 같은 로그 파일을 다시 보내면(HMI 재전송·수정본) 이전 값을 대체합니다. 다른 파일(다른 사이클)은 쌓입니다.
        for old in db.scalars(select(ParamActual).where(
                ParamActual.process_run_id == run.id, ParamActual.param_key == key, ParamActual.source == "pv",
                ParamActual.note == file.filename, ParamActual.is_deleted.is_(False),
                ParamActual.specimen_id == target.id if target else ParamActual.specimen_id.is_(None))):
            old.is_deleted = True
        actuals.add_actual(db, run, key, st["mean"], specimen=target, source="pv", method="PV", user_id=user.id,
                           stats=st, note=file.filename)
    # 원본 CSV는 공정런 첨부로 보관
    tmp = TMP_DIR / f"{uuid.uuid4().hex}.part"
    tmp.write_bytes(raw)
    name = f"{spec.short_id if spec else run.run_no}_PV_{file.filename or 'log.csv'}"
    res = file_ingest.ingest(db, tmp, name, user_id=user.id, source="hmi", default_spec=spec)
    att = db.get(Attachment, res.attachment_id) if res.attachment_id else None
    if att is not None and att.process_run_id is None:
        att.process_run_id = run.id
    run.pv_log_path = att.path if att else run.pv_log_path
    actuals.recompute_run(db, run)
    db.commit()
    return {"run_no": run.run_no, "specimen": spec.short_id if spec else None, "summary": summary, "warnings": warns}


# ── PPT (3단계) ────────────────────────────────────────────────────
@router.get("/api/test-runs/{no}/report.pptx")
def test_run_ppt(no: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tr = db.scalar(select(TestRun).where(TestRun.test_run_no == no))
    if tr is None:
        raise HTTPException(404)
    return Response(ppt.test_run_pptx(db, tr), media_type=PPTX,
                    headers={"Content-Disposition": f'attachment; filename="{no}.pptx"'})


@router.get("/api/specimens/{short_id}/report.pptx")
def specimen_ppt(short_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = workflow.find_specimen(db, short_id)
    if s is None:
        raise HTTPException(404)
    return Response(ppt.specimen_pptx(db, s), media_type=PPTX,
                    headers={"Content-Disposition": f'attachment; filename="{s.short_id}.pptx"'})


# ── X-cut 블리스터 측정 앱 결과 연동 (3단계) ──────────────────────────
class XcutRow(BaseModel):
    short_id: str
    cycle: int = 0
    blister_count: float | None = None
    blister_area_pct: float | None = None
    max_blister_mm: float | None = None
    creep_mm: float | None = None
    rating: str | None = None
    note: str | None = None


class XcutIn(BaseModel):
    test_run_no: str | None = None
    template_code: str = "XCUT_BLISTER"
    start_date: date | None = None
    equipment: str | None = "XCUT-APP"
    results: list[XcutRow]


@router.post("/api/integrations/xcut")
def xcut_import(data: XcutIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """X-cut 블리스터 품질검사 앱이 내보낸 측정값을 분석 결과로 저장.
    test_run_no가 있으면 그 분석런(템플릿 필드 이름이 같아야 함), 없으면 XCUT_BLISTER 분석런을 새로 만듭니다."""
    if data.test_run_no:
        tr = db.scalar(select(TestRun).where(TestRun.test_run_no == data.test_run_no))
        if tr is None:
            raise HTTPException(404, f"분석런 {data.test_run_no}이 없습니다.")
    else:
        tpl = db.scalar(select(TestTemplate).where(TestTemplate.code == data.template_code, TestTemplate.is_active.is_(True)))
        if tpl is None:
            raise HTTPException(422, f"템플릿 {data.template_code}이 없습니다.")
        tr = workflow.create_test_run(db, workflow.TestRunIn(
            template_id=tpl.id, equipment=data.equipment, start_date=data.start_date or date.today(),
            specimens=[{"short_id": r.short_id} for r in {r.short_id.upper(): r for r in data.results}.values()],
            note="X-cut 앱 연동"), user.id)
    saved, warnings, errors = 0, [], []
    boarded = {b.specimen.short_id for b in tr.boardings}
    for r in data.results:
        spec = workflow.find_specimen(db, r.short_id)
        if spec is None:
            errors.append(f"{r.short_id}: 시편 없음")
            continue
        if spec.short_id not in boarded:
            try:
                workflow.board(db, tr, spec, None)
            except workflow.Invalid as e:         # 폐기·소진 시편
                errors.append(f"{r.short_id}: {e}")
                continue
            boarded.add(spec.short_id)
        metrics = r.model_dump(exclude={"short_id", "cycle"}, exclude_none=True)
        try:
            _, w = workflow.save_result(db, tr, spec, r.cycle, metrics, user.id)
            warnings += w
            saved += 1
        except MetricsError as e:
            errors += [f"{r.short_id} W{r.cycle:02d}: {x}" for x in e.errors]
    if errors:
        db.rollback()
        raise HTTPException(422, {"errors": errors})
    db.commit()
    return {"test_run_no": tr.test_run_no, "saved": saved, "warnings": sorted(set(warnings))}
