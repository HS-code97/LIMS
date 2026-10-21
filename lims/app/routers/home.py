"""내 작업(홈), 로그인."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import optional_user, require_user, verify_password
from ..db import get_db
from ..models import (Attachment, ProcessRun, RunSpecimen, Specimen, TestResult, TestRun, User)
from ..web import render

router = APIRouter()


@router.get("/login")
def login_page(request: Request, next: str = "/", user: User | None = Depends(optional_user)):
    if user:
        return RedirectResponse(next or "/", 303)
    return render(request, "login.html", next=next)


@router.post("/login")
def login(request: Request, emp_no: str = Form(...), password: str = Form(...), next: str = Form("/"),
          db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.emp_no == emp_no.strip(), User.is_active.is_(True)))
    if u is None or not verify_password(password, u.pw_hash):
        return render(request, "login.html", status_code=401, next=next, error="사번 또는 비밀번호가 맞지 않습니다.",
                      emp_no=emp_no)
    request.session["uid"] = u.id
    return RedirectResponse(next if next.startswith("/") else "/", 303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@router.get("/")
def home(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    my_runs = db.scalars(select(TestRun).where(TestRun.owner_id == user.id, TestRun.status == "RUNNING")
                         .order_by(TestRun.start_date.desc())).all()
    # 내 진행 중 시험런의 빈칸 수 (본인 화면에서만 보이는 유일한 누락 표시, D-16)
    run_stats = []
    for tr in my_runs:
        n_spec = len([b for b in tr.boardings if b.unloaded_at is None])
        filled = db.scalar(select(func.count(TestResult.id)).where(TestResult.test_run_id == tr.id,
                                                                    TestResult.is_deleted.is_(False)))
        total = n_spec * (tr.cycles or 1)
        run_stats.append({"run": tr, "n_spec": n_spec, "filled": filled, "total": total})
    recent_pr = db.scalars(select(ProcessRun).where(ProcessRun.operator_id == user.id)
                           .order_by(ProcessRun.created_at.desc(), ProcessRun.id.desc()).limit(8)).all()
    unmatched = db.scalars(select(Attachment).where(Attachment.uploaded_by == user.id,
                                                    Attachment.specimen_id.is_(None),
                                                    Attachment.is_deleted.is_(False))
                           .order_by(Attachment.uploaded_at.desc())).all()
    my_specs = db.scalars(select(Specimen).where(Specimen.owner_id == user.id, Specimen.is_deleted.is_(False))
                          .order_by(Specimen.created_at.desc(), Specimen.id.desc()).limit(12)).all()
    in_test = db.scalar(select(func.count()).select_from(Specimen).where(Specimen.owner_id == user.id,
                                                                         Specimen.status == "IN_TEST"))
    others_runs = db.scalars(select(TestRun).join(RunSpecimen).join(Specimen)
                             .where(Specimen.owner_id == user.id, TestRun.owner_id != user.id,
                                    TestRun.status == "RUNNING").distinct()).all()
    return render(request, "home.html", nav="home", run_stats=run_stats, recent_pr=recent_pr,
                  unmatched=unmatched, my_specs=my_specs, in_test=in_test, others_runs=others_runs)
