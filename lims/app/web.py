"""Jinja2 템플릿 공통: 필터·전역 함수·HTMX 조각 판별."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import APP_DIR
from .services import param_dict as pdict
from .services.actuals import SOURCE_LABEL, badge_text
from .services.marking import MARK_LETTERS

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# CDN 대신 static/vendor/에 파일을 두면 그것을 씁니다(사내망 오프라인 운영).
VENDOR = {
    "htmx": ("htmx.min.js", "https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"),
    "alpine": ("alpine.min.js", "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js"),
}


def vendor(name: str) -> str:
    local, cdn = VENDOR[name]
    return f"/static/vendor/{local}" if (APP_DIR / "static" / "vendor" / local).exists() else cdn


def fmt_num(v, digits: int | None = None) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, str):
        return v
    if digits is not None:
        return f"{v:.{digits}f}"
    if float(v).is_integer():
        return f"{int(v)}"
    return f"{v:.4g}" if abs(v) < 1000 else f"{v:.1f}"


def fmt_signed(v) -> str:
    if v is None:
        return ""
    s = fmt_num(abs(v))
    return f"+{s}" if v > 0 else (f"−{s}" if v < 0 else "0")


def fmt_date(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return v or ""


def badge_class(source: str, level: str, inherited: str | None) -> str:
    if level == "target":
        return "b-target"
    if level == "run":
        return "b-session"
    if inherited:
        return "b-inherit"
    return {"test": "b-test", "lab": "b-lab", "pv": "b-pv"}.get(source, "b-actual")


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


templates.env.filters.update(num=fmt_num, signed=fmt_signed, d=fmt_date,
                             tojson_compact=lambda v: json.dumps(v, ensure_ascii=False))
from .db import engine  # noqa: E402

# 강종 입력 자동완성 예시 (base.html의 datalist#steel-grades). 목록에 없는 강종도 그대로 입력할 수 있습니다.
STEEL_GRADES = ("SPCC", "340Y", "420Y", "590DP", "780DP", "1180 TRIP")

templates.env.globals.update(vendor=vendor, pdict=pdict, db_kind=engine.dialect.name, badge_text=badge_text, badge_class=badge_class,
                             SOURCE_LABEL=SOURCE_LABEL, Path=Path, today=date.today, STEEL_GRADES=STEEL_GRADES,
                             mark_letters=MARK_LETTERS)


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx.setdefault("nav", "")
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
