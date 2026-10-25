"""시편 입고·목록·상세·계보·자르기·공정(열처리·전처리·도장)·이벤트, 각인 CSV·라벨
(시편번호 체계 v3.0, 5.1 #3, 7장 P2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import can_edit, ensure_can_edit, require_admin, require_user
from ..db import get_db
from ..models import (Attachment, Material, MasterCode, ProcessRun, ProcessVariant, Project, RunSpecimen, Specimen,
                      SpecimenEvent, TestResult, TestRun, User)
from ..schemas import EventIn, IntakeIn, SplitIn, TreatIn
from ..services import actuals, export, lineage, marking, numbering, workflow
from ..services import param_dict as pdict
from ..services.templates_engine import cell_text
from ..web import render

router = APIRouter()

# 직접 넣는 이벤트. HEAT·PRETREAT·PAINT는 단계·꼬리를 바꾸는 공정(workflow.treat), PLATE·USE는 시스템이 남김.
EVENT_TYPES = {"HEAT": "열처리", "PRETREAT": "전처리(화성 등)", "PAINT": "도장", "MOVE": "보관 이동",
               "SCRAP": "폐기", "NOTE": "메모"}
EVENT_NAMES = EVENT_TYPES | {"PLATE": "도금", "UNPLATE": "도금 취소", "CUT": "전단·자르기", "USE": "사용(과제·담당 변경)",
                             "POST_TREAT": "후처리(이전 기록)"}
STATUSES = ("AVAILABLE", "IN_TEST", "CONSUMED", "SCRAP")


def get_spec(db: Session, short_id: str) -> Specimen:
    s = workflow.find_specimen(db, short_id)
    if s is None:
        raise HTTPException(404, f"시편 {short_id}이 없습니다.")
    return s


@router.get("/specimens")
def list_page(request: Request, project: str = "", stage: str = "", status: str = "", mine: int = 0,
              deleted: int = 0, coil: str = "", plated: str = "", user: User = Depends(require_user),
              db: Session = Depends(get_db)):
    """시편 재고: 단계·상태·코일·도금 여부로 거름. 보관함에 있는 쓸 수 있는 시편 찾기(상태 AVAILABLE)."""
    deleted = int(bool(deleted and user.is_admin))      # 삭제한 시편 보기·되살리기는 관리자만
    q = select(Specimen).where(Specimen.is_deleted.is_(bool(deleted)))
    if project:
        q = q.where(Specimen.project_code == project.upper())
    if stage:
        q = q.where(Specimen.stage == stage)
    if status:
        q = q.where(Specimen.status == status)
    if mine:
        q = q.where(Specimen.owner_id == user.id)
    if coil:
        q = q.where(Specimen.coil_code == coil.strip().upper())
    specs = db.scalars(q.order_by(Specimen.created_at.desc(), Specimen.id.desc()).limit(500)).all()
    if plated in ("0", "1"):         # 거친 공정은 JSON이라 파이썬에서 거름
        specs = [s for s in specs if s.has_step("PLATE") == (plated == "1")]
    projects = db.scalars(select(Project).order_by(Project.project_code.desc())).all()
    coils = db.scalars(select(Material).where(Material.coil_code.is_not(None)).order_by(Material.coil_code)).all()
    return render(request, "specimens.html", nav="spec", specs=specs, projects=projects, coils=coils, f=dict(
        project=project, stage=stage, status=status, mine=mine, deleted=deleted, coil=coil, plated=plated),
        statuses=STATUSES, STAGES=marking.STAGES)


@router.get("/specimens/intake")
def intake_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.is_common, Project.project_code.desc())).all()
    coils = db.scalars(select(Material).where(Material.coil_code.is_not(None))
                       .order_by(Material.received_date.desc().nulls_last(), Material.id.desc()).limit(50)).all()
    return render(request, "specimen_intake.html", nav="spec", projects=projects, coils=coils)


@router.get("/specimens/shear")
def shear_page(request: Request, sid: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    """전단: 모시편을 골라 자식 시편(전폭 → 블랭크, 그 뒤 후절단·분석조각)을 일괄 생성. 로직은 split API 재사용."""
    projects = db.scalars(select(Project).order_by(Project.is_common, Project.project_code.desc())).all()
    coils = db.scalars(select(Material).where(Material.coil_code.is_not(None)).order_by(Material.coil_code)).all()
    return render(request, "specimen_shear.html", nav="shear", projects=projects, coils=coils, sid=sid.strip().upper())


def shear_json(s: Specimen) -> dict:
    """전단 화면의 모시편 정보: 다음 번호 제안·번호 자리 이름·상한."""
    level = numbering.child_level(s)
    out = spec_json(s) | {"children": sum(not c.is_deleted for c in s.children), "level": level}
    if level is not None:
        name, _, hi = numbering.LEVELS[level]
        out |= {"level_name": name, "max": hi, "child_stage": "B" if s.stage == "A" else s.stage}
    return out


@router.get("/api/shear/candidates")
def shear_candidates(coil: str = "", project: str = "", wide: int = 0, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    """자를 수 있는 모시편: 기본은 쓸 수 있는 전폭시편(A), wide=1이면 블랭크·실험편까지(분석조각·폐기·소진 제외)."""
    q = select(Specimen).where(Specimen.is_deleted.is_(False), Specimen.status.not_in(("SCRAP", "CONSUMED")))
    if not wide:
        q = q.where(Specimen.stage == "A")
    if coil:
        q = q.where(Specimen.coil_code == coil.strip().upper())
    if project:
        q = q.where(Specimen.project_code == project.strip().upper())
    specs = db.scalars(q.order_by(Specimen.short_id).limit(300)).all()
    return [shear_json(s) for s in specs if numbering.child_level(s) is not None]


@router.get("/api/shear/parent/{short_id}")
def shear_parent(short_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """각인번호·전체번호(AA1-A6-A-A)로 모시편 찾기."""
    s = get_spec(db, short_id)
    if numbering.child_level(s) is None:
        raise HTTPException(422, f"{s.short_id}은 분석조각이라 더 자를 수 없습니다.")
    return shear_json(s)


@router.post("/api/specimens/{short_id}/restore")
def restore_spec(short_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """논리 삭제한 시편 되살리기 (관리자). 부모가 삭제돼 있으면 부모부터."""
    spec = db.scalar(select(Specimen).where(Specimen.short_id == short_id.strip().upper(),
                                            Specimen.is_deleted.is_(True)))
    if spec is None:
        raise HTTPException(404, f"삭제된 시편 {short_id}이 없습니다.")
    if spec.parent is not None and spec.parent.is_deleted:
        raise HTTPException(409, f"부모 {spec.parent.short_id}이 삭제돼 있습니다. 부모부터 되살리세요.")
    spec.is_deleted = False
    db.commit()
    return spec_json(spec)


def detail_context(db: Session, spec: Specimen) -> dict:
    lineage_nodes = [*lineage.ancestors(spec), spec]
    ids = [n.id for n in lineage_nodes]
    # 공정 조건 (목표 → 실측): 사전 순서, 값이 있는 키만
    params = []
    actual_code = None
    own_manual = {}             # 이 시편에 직접 넣은 수기 실측 (시편 상세에서 수정하는 값)
    run_keys = set()            # 세션 공통 키: 공정런 전체 값이라 시편 화면에서는 고치지 않음
    if spec.process_run is not None:
        ra = actuals.RunActuals(db, spec.process_run)
        eff = ra.all_for(spec)
        quick = pdict.quick_keys()
        for k in [*quick, *[k for k in pdict.numeric_keys() if k not in quick]]:
            if k in eff and k != "out.cw":
                params.append(eff[k])
                if pdict.actual_cfg(k)["level"] == "run":
                    run_keys.add(k)
                man = [r for r in ra.rows.get((spec.id, k), []) if r.source == "manual" and r.value is not None]
                if man:
                    own_manual[k] = man[-1].value
        actual_code = actuals.actual_condition_code(db, spec)
    # 분석 이력: 자신 + 조상 (조각 상세에서도 원판·쿠폰 분석이 한 화면에, 11.2 #7)
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
    split = None
    level = numbering.child_level(spec)
    if level is not None:
        try:
            n = numbering.next_child(db, spec, 1)
            split = {"level": level, "name": numbering.LEVELS[level][0], "start": n,
                     "max": numbering.LEVELS[level][2], "label": numbering.label_of(spec, n),
                     "stage": "B" if spec.stage == "A" else spec.stage}
        except numbering.NumberingError:
            pass
    treat_codes = {k: [(c.code, c.name) for c in db.scalars(select(MasterCode).where(
        MasterCode.category == k, MasterCode.is_active.is_(True)).order_by(MasterCode.code))]
        for k in ("HEAT", "PRETREAT", "PAINT")}
    projects = db.scalars(select(Project).order_by(Project.is_common, Project.project_code.desc())).all()
    variant = None
    if spec.condition_code and spec.variant_seq is not None:
        variant = db.scalar(select(ProcessVariant).where(ProcessVariant.family == spec.condition_code[:2],
                                                         ProcessVariant.seq == spec.variant_seq))
    return {"spec": spec, "chain": lineage.chain(spec), "tree": lineage.descendants_tree(spec), "params": params,
            "actual_code": actual_code, "variant": variant, "tests": tests, "files": files, "events": events,
            "split": split, "EVENT_TYPES": EVENT_TYPES, "EVENT_NAMES": EVENT_NAMES, "STATUSES": STATUSES,
            "processes": lineage.processes(spec), "treat_codes": treat_codes, "projects": projects,
            "TREATMENTS": marking.TREATMENTS, "run": spec.process_run, "own_manual": own_manual,
            "run_keys": run_keys}


@router.get("/specimens/{short_id}")
def detail_page(request: Request, short_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    spec = get_spec(db, short_id)
    ctx = detail_context(db, spec)
    run = spec.process_run
    return render(request, "specimen_detail.html", nav="spec", can_edit=can_edit(user, spec.owner_id),
                  can_edit_actual=bool(run) and can_edit(user, spec.owner_id, run.operator_id), **ctx)


# ── API ──────────────────────────────────────────────────────────
def spec_json(s: Specimen) -> dict:
    return {"short_id": s.short_id, "display_id": s.display_id, "engraved_label": s.engraved_label,
            "stage": s.stage, "stage_name": s.stage_name, "kind": s.kind_name, "status": s.status,
            "project_code": s.project_code, "coil_code": s.coil_code, "tail": s.tail,
            "steps": s.steps or [], "condition_code": s.condition_code, "variant_seq": s.variant_seq,
            "condition_label": s.condition_label,
            "parent": s.parent.short_id if s.parent else None,
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


@router.post("/api/specimens/intake")
def intake_api(data: IntakeIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    specs = workflow.intake(db, data, user.id)
    db.commit()
    ids = ",".join(s.short_id for s in specs)
    return {"specimens": [spec_json(s) for s in specs], "coil_code": specs[0].coil_code,
            "engrave_csv": "/api/labels/engrave.csv?ids=" + ids, "label_pdf": "/api/labels/print.pdf?ids=" + ids}


@router.get("/api/coils/suggest")
def coil_suggest(coil_no: str, count: int = 1, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """현장 코일번호 → 코일코드 제안 + 다음 전폭번호. 이미 등록된 코일이면 그 코드."""
    base, pos = marking.split_field_coil(coil_no)
    mat = db.scalar(select(Material).where(Material.coil_no == base))
    count = max(1, min(count, len(marking.MARK_LETTERS)))
    try:
        code, derived = marking.suggest_coil_code(db, base)
        sheet = numbering.next_sheet(db, code, count)
    except (marking.MarkingError, numbering.NumberingError) as e:
        raise HTTPException(422, str(e))
    return {"coil_no": base, "position": pos, "coil_code": code, "existing": bool(mat and mat.coil_code),
            "derived": derived, "sheet_start": sheet,
            "marks": [marking.mark_id(code, marking.letter_of(n)) for n in range(sheet, sheet + count)]}


@router.get("/api/plating/candidates")
def platable(coil: str = "", user: User = Depends(require_user), db: Session = Depends(get_db)):
    """도금할 블랭크(B 단계, 아직 도금 안 함, 쓸 수 있는 상태, 더 자르지 않음): 공정런 등록 화면의 [블랭크 불러오기].
    전폭시편(A)도 각인번호를 직접 넣으면 도금할 수 있습니다."""
    q = select(Specimen).where(Specimen.is_deleted.is_(False), Specimen.status == "AVAILABLE", Specimen.stage == "B")
    if coil:
        q = q.where(Specimen.coil_code == coil.strip().upper())
    specs = [s for s in db.scalars(q.order_by(Specimen.short_id).limit(300))
             if not s.has_step("PLATE") and not any(not c.is_deleted for c in s.children)]
    return [{"short_id": s.short_id, "display_id": s.display_id, "project_code": s.project_code,
             "owner": s.owner.name if s.owner else None, "storage_location": s.storage_location} for s in specs]


@router.get("/api/specimens/{short_id}/next")
def next_numbers(short_id: str, count: int = 1, start: int | None = None, user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    """자를 때 다음 빈 번호 제안 + (start를 주면) 충돌 검사."""
    parent = get_spec(db, short_id)
    count = max(count, 1)
    try:
        n = numbering.next_child(db, parent, count)
        clash = numbering.child_conflicts(db, parent, start, count) if start is not None else []
        first = start if start is not None else n
        labels = [numbering.label_of(parent, first), numbering.label_of(parent, first + count - 1)]
    except (numbering.NumberingError, marking.MarkingError) as e:
        raise HTTPException(422, str(e))
    return {"suggest": n, "conflicts": clash, "first": labels[0], "last": labels[1]}


@router.post("/api/specimens/{short_id}/split")
def split_api(short_id: str, data: SplitIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """다른 연구원도 쓸 수 있는 시편을 잘라 자기 과제로 쓸 수 있습니다(부모에 USE 이력). 부모는 바뀌지 않음."""
    parent = get_spec(db, short_id)
    kids = workflow.split(db, parent, data, user.id)
    db.commit()
    return {"children": [spec_json(k) for k in kids], "parent_status": parent.status,
            "engrave_csv": "/api/labels/engrave.csv?ids=" + ",".join(k.short_id for k in kids),
            "label_pdf": "/api/labels/print.pdf?ids=" + ",".join(k.short_id for k in kids)}


@router.post("/api/specimens/{short_id}/treat")
def treat_api(short_id: str, data: TreatIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """열처리·전처리·도장: 같은 시편의 단계·꼬리가 바뀜(각인번호 그대로). 다른 사람 시편이면 과제·담당이 넘어옴."""
    spec = workflow.treat(db, get_spec(db, short_id), data, user.id)
    db.commit()
    return spec_json(spec)


class UnplateIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@router.post("/api/specimens/{short_id}/unplate")
def unplate_api(short_id: str, data: UnplateIn | None = None, user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    """도금 취소: 공정런에서 빼고 도금 전 단계(블랭크)로 되돌림. 시편 소유자·공정런 작업자·관리자만."""
    spec = get_spec(db, short_id)
    run = spec.process_run
    ensure_can_edit(user, spec.owner_id, run.operator_id if run else None)
    run = workflow.unplate(db, spec, user.id, data.reason if data else None)
    db.commit()
    return spec_json(spec) | {"run_no": run.run_no, "panels_left": len(run.panels)}


@router.post("/api/specimens/{short_id}/events")
def add_event(short_id: str, data: EventIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    spec = get_spec(db, short_id)
    if data.event_type not in EVENT_TYPES:
        raise HTTPException(422, f"이벤트 종류: {', '.join(EVENT_TYPES)}")
    if data.event_type in marking.TREATMENTS:     # 단계·꼬리를 바꾸는 공정
        params = {k: v for k, v in data.params.items() if k != "code"}
        spec = workflow.treat(db, spec, TreatIn(kind=data.event_type, code=data.code or str(data.params.get("code", "")),
                                                event_date=data.event_date, params=params), user.id)
        db.commit()
        return {"id": None, "specimen": spec_json(spec)}
    ensure_can_edit(user, spec.owner_id)        # SCRAP·MOVE는 상태·보관 위치를 바꾸므로 소유자·관리자만
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
        return [s for s in pr.panels if not s.is_deleted], None, {}
    if test_run:
        tr = db.scalar(select(TestRun).where(TestRun.test_run_no == test_run))
        if tr is None:
            raise HTTPException(404)
        specs = [b.specimen for b in sorted(tr.boardings, key=lambda b: (b.slot or "", b.specimen.short_id))
                 if not b.specimen.is_deleted]
        slots = {b.specimen_id: b.slot for b in tr.boardings}
        return specs, tr, slots
    wanted = [x.strip().upper() for x in ids.split(",") if x.strip()]
    specs = db.scalars(select(Specimen).where(or_(*[Specimen.short_id == w for w in wanted]),
                                              Specimen.is_deleted.is_(False))).all() if wanted else []
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
