"""시편 목록·상세·계보·분기·이벤트, 각인 CSV·라벨 (3.6절, 5.1 #3, 7장 P2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import can_edit, ensure_can_edit, require_user
from ..db import get_db
from ..models import (Attachment, ProcessRun, Project, RunSpecimen, Specimen, SpecimenEvent, TestResult, TestRun,
                      User)
from ..schemas import EventIn, SplitIn
from ..services import actuals, export, lineage, numbering, workflow
from ..services import param_dict as pdict
from ..services.templates_engine import cell_text
from ..web import render

router = APIRouter()

EVENT_TYPES = {"POST_TREAT": "후처리", "PAINT": "도장", "HEAT": "열처리", "MOVE": "보관 이동", "SCRAP": "폐기",
               "NOTE": "메모"}
STATUSES = ("AVAILABLE", "IN_TEST", "CONSUMED", "SCRAP")


def get_spec(db: Session, short_id: str) -> Specimen:
    s = workflow.find_specimen(db, short_id)
    if s is None:
        raise HTTPException(404, f"시편 {short_id}이 없습니다.")
    return s


@router.get("/specimens")
def list_page(request: Request, project: str = "", stage: str = "", status: str = "", mine: int = 0,
              user: User = Depends(require_user), db: Session = Depends(get_db)):
    q = select(Specimen).where(Specimen.is_deleted.is_(False))
    if project:
        q = q.where(Specimen.project_code == project.upper())
    if stage:
        q = q.where(Specimen.stage == stage)
    if status:
        q = q.where(Specimen.status == status)
    if mine:
        q = q.where(Specimen.owner_id == user.id)
    specs = db.scalars(q.order_by(Specimen.created_at.desc(), Specimen.id.desc()).limit(500)).all()
    projects = db.scalars(select(Project).order_by(Project.project_code.desc())).all()
    return render(request, "specimens.html", nav="spec", specs=specs, projects=projects, f=dict(
        project=project, stage=stage, status=status, mine=mine), statuses=STATUSES)


def detail_context(db: Session, spec: Specimen) -> dict:
    lineage_nodes = [*lineage.ancestors(spec), spec]
    ids = [n.id for n in lineage_nodes]
    # 공정 조건 (목표 → 실측): 사전 순서, 값이 있는 키만
    params = []
    actual_code = None
    if spec.process_run is not None:
        ra = actuals.RunActuals(db, spec.process_run)
        eff = ra.all_for(spec)
        quick = pdict.quick_keys()
        for k in [*quick, *[k for k in pdict.numeric_keys() if k not in quick]]:
            if k in eff and k != "out.cw":
                params.append(eff[k])
        actual_code = actuals.actual_condition_code(db, spec)
    # 시험 이력: 자신 + 조상 (조각 상세에서도 원판·쿠폰 시험이 한 화면에, 11.2 #7)
    boardings = db.scalars(select(RunSpecimen).where(RunSpecimen.specimen_id.in_(ids))
                           .join(TestRun).order_by(TestRun.start_date.desc())).all()
    tests = []
    for b in boardings:
        tr = b.test_run
        results = db.scalars(select(TestResult).where(TestResult.test_run_id == tr.id,
                                                      TestResult.specimen_id == b.specimen_id,
                                                      TestResult.is_deleted.is_(False))
                             .order_by(TestResult.cycle_no)).all()
        last = next((r for r in reversed(results) if r.metrics), None)
        tests.append({"b": b, "run": tr, "results": results, "last": last,
                      "last_text": cell_text(tr.template, last.metrics) if last else "",
                      "own": b.specimen_id == spec.id})
    files = db.scalars(select(Attachment).where(Attachment.specimen_id.in_(ids), Attachment.is_deleted.is_(False))
                       .order_by(Attachment.uploaded_at.desc(), Attachment.id.desc())).all()
    events = db.scalars(select(SpecimenEvent).where(SpecimenEvent.specimen_id.in_(ids))
                        .order_by(SpecimenEvent.event_date.desc(), SpecimenEvent.id.desc())).all()
    split_suggest = {}
    for st in {"P": ("C", "S"), "C": ("S",), "S": ()}[spec.stage]:
        try:
            split_suggest[st] = numbering.next_free(db, spec.project_code, st, 1, prefer=int(spec.serial_no))
        except numbering.NumberingError:
            pass
    return {"spec": spec, "chain": lineage.chain(spec), "tree": lineage.descendants_tree(spec), "params": params,
            "actual_code": actual_code, "tests": tests, "files": files, "events": events,
            "split_suggest": split_suggest, "EVENT_TYPES": EVENT_TYPES, "STATUSES": STATUSES}


@router.get("/specimens/{short_id}")
def detail_page(request: Request, short_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    spec = get_spec(db, short_id)
    ctx = detail_context(db, spec)
    return render(request, "specimen_detail.html", nav="spec", can_edit=can_edit(user, spec.owner_id), **ctx)


# ── API ──────────────────────────────────────────────────────────
def spec_json(s: Specimen) -> dict:
    return {"short_id": s.short_id, "display_id": s.display_id, "engraved_label": s.engraved_label,
            "stage": s.stage, "status": s.status, "project_code": s.project_code,
            "condition_code": s.condition_code, "parent": s.parent.short_id if s.parent else None,
            "process_run": s.process_run.run_no if s.process_run else None,
            "material": s.material.coil_no if s.material else None, "size_text": s.size_text,
            "sample_position": s.sample_position, "rolling_direction": s.rolling_direction,
            "surface_side": s.surface_side, "storage_location": s.storage_location,
            "owner": s.owner.name if s.owner else None}


@router.get("/api/specimens/{short_id}")
def get_spec_api(short_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ctx = detail_context(db, get_spec(db, short_id))
    s = ctx["spec"]
    return spec_json(s) | {
        "lineage": [n["label"] for n in ctx["chain"]],
        "children": [c.short_id for c in s.children if not c.is_deleted],
        "actual_condition_code": ctx["actual_code"],
        "tests": [{"test_run_no": t["run"].test_run_no, "slot": t["b"].slot, "specimen": t["b"].specimen.short_id,
                   "results": {r.cycle_no: r.metrics for r in t["results"]}} for t in ctx["tests"]],
        "files": [{"id": a.id, "name": a.original_name, "kind": a.kind, "specimen": a.specimen.short_id}
                  for a in ctx["files"]],
    }


@router.get("/api/specimens/{short_id}/params")
def get_params(short_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    spec = get_spec(db, short_id)
    if spec.process_run is None:
        return {}
    ra = actuals.RunActuals(db, spec.process_run)
    return {k: {"label": pdict.label(k), "target": e.target, "actual": e.actual, "effective": e.effective,
                "source": e.source, "level": e.level, "inherited_from": e.inherited_from, "badge": e.badge,
                "deviation": e.deviation, "out_of_tol": e.out_of_tol, "intended_change": e.is_override}
            for k, e in ra.all_for(spec).items()}


@router.post("/api/specimens/{short_id}/split")
def split_api(short_id: str, data: SplitIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    parent = get_spec(db, short_id)
    kids = workflow.split(db, parent, data, user.id)
    db.commit()
    return {"children": [spec_json(k) for k in kids], "parent_status": parent.status,
            "engrave_csv": "/api/labels/engrave.csv?ids=" + ",".join(k.short_id for k in kids),
            "label_pdf": "/api/labels/print.pdf?ids=" + ",".join(k.short_id for k in kids)}


@router.post("/api/specimens/{short_id}/events")
def add_event(short_id: str, data: EventIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    spec = get_spec(db, short_id)
    if data.event_type not in EVENT_TYPES:
        raise HTTPException(422, f"이벤트 종류: {', '.join(EVENT_TYPES)}")
    ev = SpecimenEvent(specimen_id=spec.id, event_type=data.event_type, params=data.params,
                       event_date=data.event_date, user_id=user.id)
    db.add(ev)
    if data.event_type == "SCRAP":
        spec.status = "SCRAP"
    if data.event_type == "MOVE" and data.params.get("location"):
        spec.storage_location = str(data.params["location"])[:100]
    db.commit()
    return {"id": ev.id}


class SpecPatch(BaseModel):
    status: str | None = None
    storage_location: str | None = None
    note: str | None = None
    is_deleted: bool | None = None


@router.patch("/api/specimens/{short_id}")
def patch_spec(short_id: str, data: SpecPatch, user: User = Depends(require_user), db: Session = Depends(get_db)):
    spec = get_spec(db, short_id)
    ensure_can_edit(user, spec.owner_id)
    if data.status is not None:
        if data.status not in STATUSES:
            raise HTTPException(422, "상태값 오류")
        spec.status = data.status
    if data.storage_location is not None:
        spec.storage_location = data.storage_location[:100]
    if data.note is not None:
        spec.note = data.note
    if data.is_deleted:
        if any(not c.is_deleted for c in spec.children):
            raise HTTPException(409, "자식 시편이 있어 삭제할 수 없습니다.")
        spec.is_deleted = True
    db.commit()
    return spec_json(spec)


# ── 각인 CSV · 라벨 ───────────────────────────────────────────────
def _label_targets(db: Session, ids: str, run: str, test_run: str) -> tuple[list[Specimen], TestRun | None, dict]:
    tr, slots = None, {}
    if run:
        pr = db.scalar(select(ProcessRun).where(ProcessRun.run_no == run))
        if pr is None:
            raise HTTPException(404)
        return list(pr.panels), None, {}
    if test_run:
        tr = db.scalar(select(TestRun).where(TestRun.test_run_no == test_run))
        if tr is None:
            raise HTTPException(404)
        specs = [b.specimen for b in sorted(tr.boardings, key=lambda b: (b.slot or "", b.specimen.short_id))]
        slots = {b.specimen_id: b.slot for b in tr.boardings}
        return specs, tr, slots
    wanted = [x.strip().upper() for x in ids.split(",") if x.strip()]
    specs = db.scalars(select(Specimen).where(or_(*[Specimen.short_id == w for w in wanted]))).all() if wanted else []
    order = {w: i for i, w in enumerate(wanted)}
    return sorted(specs, key=lambda s: order.get(s.short_id, 0)), None, {}


@router.get("/api/labels/engrave.csv")
def engrave_csv(ids: str = "", run: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    specs, _, _ = _label_targets(db, ids, run, "")
    data = export.engrave_csv(specs)
    name = f"engrave_{run or 'specimens'}.csv"
    from ..config import ENGRAVE_ENCODING
    charset = "cp949" if ENGRAVE_ENCODING.lower() in ("cp949", "euc-kr") else "utf-8"
    return Response(data, media_type=f"text/csv; charset={charset}",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/labels/print.pdf")
def labels_pdf(ids: str = "", run: str = "", test_run: str = "", user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    specs, tr, slots = _label_targets(db, ids, run, test_run)
    if not specs:
        raise HTTPException(422, "라벨을 만들 시편이 없습니다.")
    pdf = export.labels_pdf(specs, tr, slots)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="labels_{test_run or run or "specimens"}.pdf"'})
