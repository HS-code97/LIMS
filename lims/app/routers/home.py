"""내 작업(홈), 로그인."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import optional_user, require_user, verify_password
from ..db import get_db
from ..models import (Attachment, ProcessRun, RunSpecimen, Specimen, TestResult, TestRun, User)
from ..web import render

router = APIRouter()

# 로그인 실패 제한: 같은 사번·주소로 10분에 5번 틀리면 10분 동안 막음 (프로세스 메모리, worker마다 따로 셈)
MAX_FAILS, FAIL_WINDOW = 5, 600
_fails: dict[tuple[str, str], list[float]] = defaultdict(list)


def safe_next(next: str | None) -> str:
    """로그인 뒤 이동할 주소는 이 사이트 안 경로만 (//evil.com, /\\evil.com, https://… 는 /로)."""
    if not next or not next.startswith("/") or next.startswith(("//", "/\\")):
        return "/"
    return next


def _recent_fails(key: tuple[str, str]) -> list[float]:
    now = time.monotonic()
    _fails[key] = [t for t in _fails[key] if now - t < FAIL_WINDOW]
    return _fails[key]


@router.get("/login")
def login_page(request: Request, next: str = "/", user: User | None = Depends(optional_user)):
    if user:
        return RedirectResponse(safe_next(next), 303)
    return render(request, "login.html", next=safe_next(next))


@router.post("/login")
def login(request: Request, emp_no: str = Form(...), password: str = Form(...), next: str = Form("/"),
          db: Session = Depends(get_db)):
    key = (emp_no.strip().lower(), request.client.host if request.client else "")
    if len(_recent_fails(key)) >= MAX_FAILS:
        return render(request, "login.html", status_code=429, next=safe_next(next), emp_no=emp_no,
                      error="로그인을 여러 번 틀렸습니다. 10분 뒤에 다시 시도하세요.")
    u = db.scalar(select(User).where(User.emp_no == emp_no.strip(), User.is_active.is_(True)))
    if u is None or not verify_password(password, u.pw_hash):
        _fails[key].append(time.monotonic())
        return render(request, "login.html", status_code=401, next=safe_next(next),
                      error="사번 또는 비밀번호가 맞지 않습니다.", emp_no=emp_no)
    _fails.pop(key, None)
    request.session["uid"] = u.id
    return RedirectResponse(safe_next(next), 303)


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
