"""FastAPI 앱: 라우터 등록, 정적 파일, 로그인 리다이렉트."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .auth import LoginRequired
from .config import APP_DIR, SECRET_KEY
from .db import Base, engine
from .routers import (admin, analysis, files, home, presets, process_runs, search, specimens,
                      templates_admin, test_runs)
from .services.workflow import Conflict, Invalid

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 운영(PostgreSQL)은 Alembic 마이그레이션을 씁니다. 개발용 SQLite는 없으면 만듭니다.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title="도금강판 R&D LIMS", version="2.2", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="lims_session",
                   max_age=14 * 24 * 3600, same_site="lax")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

for r in (home, process_runs, presets, specimens, test_runs, files, search, admin, templates_admin, analysis):
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
