"""시험 템플릿 편집 (2단계, D-24). 고치면 새 버전이 생기고 기존 결과는 저장 당시 버전으로 해석합니다."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Team, TestTemplate, User
from ..services import param_dict as pdict
from ..web import render

router = APIRouter()
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,29}$")
TYPE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,19}$")
FIELD_TYPES = ("number", "select", "text", "bool")


class FieldIn(BaseModel):
    key: str
    label: str
    type: str = "number"
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None
    grid: bool = False
    maps_to: str | None = None
    default: Any = None


class TemplateIn(BaseModel):
    code: str
    name: str
    test_type: str
    team_id: int | None = None
    default_cycles: int | None = 1
    default_interval_days: int | None = None
    field_schema: list[FieldIn]
    condition_schema: list[FieldIn] = []


def validate_template(data: TemplateIn) -> list[str]:
    errs = []
    if not CODE_RE.match(data.code):
        errs.append("코드는 영문 대문자·숫자·_ (예: CCT_STD)")
    if not TYPE_RE.match(data.test_type):
        errs.append("시험 종류는 영문 대문자·숫자 (예: CCT) — 시험런 번호 TR-{종류}-YY### 에 쓰입니다")
    if not data.field_schema:
        errs.append("결과 필드가 하나 이상 있어야 합니다")
    for group, fields in (("결과", data.field_schema), ("운전조건", data.condition_schema)):
        seen = set()
        for f in fields:
            if not KEY_RE.match(f.key):
                errs.append(f"{group} 키 '{f.key}': 영문 소문자로 시작, 소문자·숫자·_ (예: red_rust_pct)")
            if f.key in seen:
                errs.append(f"{group} 키 '{f.key}' 중복")
            seen.add(f.key)
            if f.type not in FIELD_TYPES:
                errs.append(f"{group} '{f.key}' 형식: {', '.join(FIELD_TYPES)}")
            if f.type == "select" and not f.options:
                errs.append(f"{group} '{f.key}': 선택형은 선택지가 필요합니다")
            if f.min is not None and f.max is not None and f.min > f.max:
                errs.append(f"{group} '{f.key}': 최소 > 최대")
            if f.maps_to:
                if group != "결과":
                    errs.append("maps_to는 결과 필드에만 지정합니다")
                elif not pdict.is_numeric(f.maps_to) or f.type != "number":
                    errs.append(f"'{f.key}' maps_to '{f.maps_to}': 파라미터 사전의 숫자 키, 숫자 필드만 가능")
    return errs


def _clean(fields: list[FieldIn]) -> list[dict]:
    out = []
    for f in fields:
        d = {"key": f.key, "label": f.label, "type": f.type}
        for k in ("unit", "min", "max", "options", "maps_to", "default"):
            v = getattr(f, k)
            if v not in (None, "", []):
                d[k] = v
        if f.grid:
            d["grid"] = True
        out.append(d)
    return out


@router.get("/admin/templates/edit")
def editor(request: Request, id: int | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    tpl = db.get(TestTemplate, id) if id else None
    data = ({"code": tpl.code, "name": tpl.name, "test_type": tpl.test_type, "team_id": tpl.team_id,
             "default_cycles": tpl.default_cycles, "default_interval_days": tpl.default_interval_days,
             "field_schema": tpl.field_schema, "condition_schema": tpl.condition_schema or [], "version": tpl.version}
            if tpl else {"code": "", "name": "", "test_type": "", "team_id": user.team_id, "default_cycles": 1,
                         "default_interval_days": None, "field_schema": [], "condition_schema": [], "version": 0})
    teams = db.scalars(select(Team).order_by(Team.name)).all()
    # maps_to 대상: 실측을 받는 숫자 키 (actual 블록이 있거나 출력 특성 구간)
    keys = [{"key": k, "label": f"{p['section_nm']} {p['l']} ({p['u']})"} for k, p in pdict.params().items()
            if pdict.is_numeric(k) and (p.get("actual") or not p.get("setpoint", True))]
    return render(request, "template_editor.html", nav="admin", data=data, teams=teams, dict_keys=keys)


@router.post("/api/test-templates")
def save_template(data: TemplateIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """같은 코드가 있으면 버전 +1 (기존 버전은 그대로 두고 비활성), 없으면 v1. 팀원 누구나 자기 팀 템플릿을 고칠 수 있습니다."""
    data.code = data.code.strip().upper()
    data.test_type = data.test_type.strip().upper()
    errs = validate_template(data)
    if errs:
        raise HTTPException(422, {"errors": errs})
    latest = db.scalar(select(TestTemplate).where(TestTemplate.code == data.code)
                       .order_by(TestTemplate.version.desc()).limit(1))
    if latest and not (user.is_admin or latest.team_id in (None, user.team_id)):
        raise HTTPException(403, "다른 팀 템플릿은 그 팀원이나 관리자만 고칠 수 있습니다.")
    version = (db.scalar(select(func.max(TestTemplate.version)).where(TestTemplate.code == data.code)) or 0) + 1
    for old in db.scalars(select(TestTemplate).where(TestTemplate.code == data.code)):
        old.is_active = False
    t = TestTemplate(code=data.code, version=version, name=data.name, test_type=data.test_type,
                     field_schema=_clean(data.field_schema), condition_schema=_clean(data.condition_schema),
                     default_cycles=data.default_cycles, default_interval_days=data.default_interval_days,
                     team_id=data.team_id, is_active=True)
    db.add(t)
    db.commit()
    return {"id": t.id, "code": t.code, "version": t.version}


@router.post("/api/test-templates/{tid}/toggle")
def toggle_template(tid: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    t = db.get(TestTemplate, tid)
    if t is None:
        raise HTTPException(404)
    if not (user.is_admin or t.team_id in (None, user.team_id)):
        raise HTTPException(403)
    t.is_active = not t.is_active
    db.commit()
    return {"id": t.id, "is_active": t.is_active}
