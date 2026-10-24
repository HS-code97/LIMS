"""FastAPI 앱: 라우터 등록, 정적 파일, 로그인 리다이렉트."""
from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, IntegrityError
from starlette.middleware.sessions import SessionMiddleware

from .auth import LoginRequired
from .config import API_DOCS, APP_DIR, COOKIE_SECURE, session_secret
from .db import Base, engine
from .errors import Conflict, Invalid
from .routers import (admin, analysis, files, guide, home, presets, process_runs, search, specimens,
                      templates_admin, test_runs)

log = logging.getLogger("lims")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 운영(PostgreSQL)은 Alembic 마이그레이션을 씁니다. 개발용 SQLite는 없으면 만듭니다.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    yield


_docs = {} if API_DOCS else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="도금강판 R&D LIMS", version="2.3", lifespan=lifespan, **_docs)
app.add_middleware(SessionMiddleware, secret_key=session_secret(), session_cookie="lims_session",
                   max_age=14 * 24 * 3600, same_site="lax", https_only=COOKIE_SECURE)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

for r in (home, guide, process_runs, presets, specimens, test_runs, files, search, admin, templates_admin, analysis):
    app.include_router(r.router)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


@app.exception_handler(Conflict)
async def _conflict(_request: Request, exc: Conflict):
    return JSONResponse({"detail": str(exc), "conflicts": exc.items}, status_code=409)


@app.exception_handler(Invalid)
async def _invalid(_request: Request, exc: Invalid):
    return JSONResponse({"detail": str(exc), "items": exc.items}, status_code=422)


def _json_safe(v):
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


@app.exception_handler(RequestValidationError)
async def _request_invalid(_request: Request, exc: RequestValidationError):
    # 기본 처리기는 입력값을 그대로 돌려주는데, 입력이 NaN이면 응답 JSON을 만들지 못해 500이 됩니다.
    return JSONResponse({"detail": _json_safe(jsonable_encoder(exc.errors()))}, status_code=422)


@app.exception_handler(IntegrityError)
async def _integrity(_request: Request, exc: IntegrityError):
    # 번호·파일 해시 중복 검사와 저장 사이에 다른 사용자가 먼저 저장한 경우 (UNIQUE·FK 위반)
    log.warning("IntegrityError: %s", exc.orig)
    return JSONResponse({"detail": "다른 사용자가 같은 번호나 파일을 먼저 저장했거나 참조 대상이 없습니다. "
                                   "새로고침한 뒤 다시 시도하세요.", "conflicts": []}, status_code=409)


@app.exception_handler(DataError)
async def _data_error(_request: Request, exc: DataError):
    log.warning("DataError: %s", exc.orig)
    return JSONResponse({"detail": "저장할 수 없는 값이 있습니다(길이·형식).", "items": []}, status_code=422)
