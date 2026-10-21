"""파일 업로드·자동 매칭·미분류함·내려받기 (7장 P5)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..config import FILES_DIR, MAX_UPLOAD_MB, TMP_DIR
from ..db import get_db
from ..models import Attachment, TestResult, TestRun, User
from ..schemas import LinkIn
from ..services import file_ingest, workflow
from ..services.thumbnails import large_of

router = APIRouter()


@router.post("/api/files")
async def upload(files: list[UploadFile] = File(...), test_run_no: str = Form(""), short_id: str = Form(""),
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    """다중 업로드(드래그&드롭·폴더) → 파일마다 매칭/미분류/중복 결과."""
    default_spec = workflow.find_specimen(db, short_id) if short_id else None
    tr = None
    if test_run_no:
        tr = db.scalar(select(TestRun).where(TestRun.test_run_no == test_run_no))
        if tr is None:
            raise HTTPException(404, f"시험런 {test_run_no}이 없습니다.")
    out = []
    limit = MAX_UPLOAD_MB * 1024 * 1024
    for f in files:
        name = (f.filename or "noname").replace("\\", "/").split("/")[-1]
        tmp = TMP_DIR / f"{uuid.uuid4().hex}.part"
        size = 0
        with open(tmp, "wb") as fh:
            while chunk := await f.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    break
                fh.write(chunk)
        if size > limit:
            tmp.unlink(missing_ok=True)
            out.append({"name": name, "status": "error", "message": f"{MAX_UPLOAD_MB} MB 초과"})
            continue
        r = file_ingest.ingest(db, tmp, name, user_id=user.id, test_run=tr, default_spec=default_spec)
        db.commit()
        out.append(r.as_dict())
    summary = {s: sum(1 for o in out if o["status"] == s) for s in ("matched", "unmatched", "duplicate", "error")}
    return {"results": out, "summary": summary}


@router.patch("/api/files/{att_id}")
def link_file(att_id: int, data: LinkIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """미분류 파일을 시편(·결과 셀)에 연결."""
    att = db.get(Attachment, att_id)
    if att is None or att.is_deleted:
        raise HTTPException(404)
    spec = workflow.find_specimen(db, data.short_id)
    if spec is None:
        raise HTTPException(422, f"시편 {data.short_id}이 없습니다.")
    result = None
    if data.test_run_no and data.cycle_no is not None:
        tr = db.scalar(select(TestRun).where(TestRun.test_run_no == data.test_run_no))
        if tr is None:
            raise HTTPException(422, "시험런이 없습니다.")
        result = db.scalar(select(TestResult).where(TestResult.test_run_id == tr.id, TestResult.specimen_id == spec.id,
                                                    TestResult.cycle_no == data.cycle_no))
        if result is None:
            result, _ = workflow.save_result(db, tr, spec, data.cycle_no, {}, user.id)
    file_ingest.link(db, att, spec, result)
    db.commit()
    return {"id": att.id, "short_id": spec.short_id}


@router.delete("/api/files/{att_id}")
def delete_file(att_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    att = db.get(Attachment, att_id)
    if att is None:
        raise HTTPException(404)
    if not (user.is_admin or att.uploaded_by == user.id):
        raise HTTPException(403, "올린 사람만 지울 수 있습니다.")
    att.is_deleted = True       # 논리 삭제 (원본 파일은 남김, D-20)
    db.commit()
    return {"ok": True}


def _path(att: Attachment, which: str):
    rel = {"orig": att.path, "thumb": att.thumb_path, "large": large_of(att.thumb_path)}[which]
    if not rel:
        raise HTTPException(404)
    p = (FILES_DIR / rel).resolve()
    if FILES_DIR.resolve() not in p.parents or not p.exists():
        raise HTTPException(404)
    return p


@router.get("/files/{att_id}")
def download(att_id: int, dl: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db)):
    att = db.get(Attachment, att_id)
    if att is None:
        raise HTTPException(404)
    return FileResponse(_path(att, "orig"), filename=att.original_name,
                        content_disposition_type="attachment" if dl else "inline")


@router.get("/files/{att_id}/thumb")
def thumb(att_id: int, size: str = "s", user: User = Depends(require_user), db: Session = Depends(get_db)):
    att = db.get(Attachment, att_id)
    if att is None:
        raise HTTPException(404)
    return FileResponse(_path(att, "large" if size == "l" else "thumb"), media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})
