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


def _pk(obj):
    """기본키 값. flush 직후라 새 행도 채워져 있습니다(identity는 아직 없음). 복합키는 리스트."""
    vals = inspect(obj).mapper.primary_key_from_instance(obj)
    return vals[0] if len(vals) == 1 else list(vals)


def _row_id(pk) -> int:
    """정수 단일키만 row_id에 넣고, 문자열·복합키(projects, master_codes)는 0 + before/after의 _pk로 식별."""
    return pk if isinstance(pk, int) and not isinstance(pk, bool) else 0


def _snapshot(obj) -> dict:
    return {c.key: _jsonable(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs}


@event.listens_for(Session, "after_flush")
def _audit_after_flush(session: Session, _ctx):
    from .common import AuditLog

    rows = []
    # 웹 요청은 auth가 세션에 적은 사용자, 스크립트·감시·테스트는 contextvar
    uid = session.info["user_id"] if "user_id" in session.info else current_user_id.get()
    for obj in session.new:
        t = getattr(obj, "__tablename__", None)
        if not t or t in SKIP_TABLES:
            continue
        rows.append(dict(table_name=t, row_id=_row_id(_pk(obj)), action="INSERT", before=None,
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
        pk = _pk(obj)
        if not _row_id(pk):
            before["_pk"] = after["_pk"] = pk
        rows.append(dict(table_name=t, row_id=_row_id(pk), action=action, before=before, after=after, user_id=uid))
    if rows:
        session.connection().execute(AuditLog.__table__.insert(), rows)
