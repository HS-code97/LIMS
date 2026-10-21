"""세션, Base, 공용 컬럼 타입."""
from __future__ import annotations

from contextvars import ContextVar

from sqlalchemy import JSON, Numeric, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

# PostgreSQL에서는 JSONB, 그 밖(개발용 SQLite)에서는 JSON
JSONType = JSON().with_variant(JSONB(), "postgresql")
# NUMERIC 컬럼을 float로 다룸 (Decimal 변환 비용·혼용 방지)
Num = Numeric(asdecimal=False)

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# 감사 로그가 기록할 현재 사용자 (요청마다 auth가 설정)
current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
