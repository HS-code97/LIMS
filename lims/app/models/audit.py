"""감사 로그: SQLAlchemy after_flush 이벤트에서 자동 기록 (8장 운영 규칙)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from ..db import current_user_id

SKIP_TABLES = {"audit_log", "effective_params"}


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool, dict, list)) or v is None:
        return v
    return str(v)


def _row_id(obj) -> int:
    ident = inspect(obj).identity
    if not ident:
        return 0
    first = ident[0]
    return first if isinstance(first, int) else 0


def _snapshot(obj) -> dict:
    return {c.key: _jsonable(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs}


@event.listens_for(Session, "after_flush")
def _audit_after_flush(session: Session, _ctx):
    from .common import AuditLog

    rows = []
    uid = current_user_id.get()
    for obj in session.new:
        t = getattr(obj, "__tablename__", None)
        if not t or t in SKIP_TABLES:
            continue
        rows.append(dict(table_name=t, row_id=_row_id(obj), action="INSERT", before=None,
                         after=_snapshot(obj), user_id=uid))
    for obj in session.dirty:
        t = getattr(obj, "__tablename__", None)
        if not t or t in SKIP_TABLES or not session.is_modified(obj, include_collections=False):
            continue
        st = inspect(obj)
        before, after = {}, {}
        for attr in st.mapper.column_attrs:
            hist = st.attrs[attr.key].history
            if hist.has_changes():
                before[attr.key] = _jsonable(hist.deleted[0]) if hist.deleted else None
                after[attr.key] = _jsonable(hist.added[0]) if hist.added else None
        if not after:
            continue
        action = "DELETE" if after.get("is_deleted") is True else "UPDATE"
        rows.append(dict(table_name=t, row_id=_row_id(obj), action=action, before=before, after=after, user_id=uid))
    if rows:
        session.connection().execute(AuditLog.__table__.insert(), rows)
