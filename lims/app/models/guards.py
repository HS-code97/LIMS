"""flush 직전 값 검사: 문자열 길이와 NaN·무한대.

개발용 SQLite는 VARCHAR 길이를 무시하고 NaN을 그대로(또는 NULL로) 저장하지만, 운영 PostgreSQL은
같은 값을 DataError(500)로 거부합니다. 어느 경로(API·엑셀·감시)로 들어오든 저장 전에 422로 막아
두 DB의 동작을 맞춥니다.
"""
from __future__ import annotations

import math

from sqlalchemy import JSON, String, event, inspect
from sqlalchemy.orm import Session

from ..errors import Invalid


def _bad_number(v) -> bool:
    return isinstance(v, float) and not math.isfinite(v)


def _json_has_bad_number(v) -> bool:
    if isinstance(v, dict):
        return any(_json_has_bad_number(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return any(_json_has_bad_number(x) for x in v)
    return _bad_number(v)


def problems(obj) -> list[str]:
    mapper = inspect(obj).mapper
    out = []
    for attr in mapper.column_attrs:
        col = attr.columns[0]
        if col.computed is not None:
            continue
        v = getattr(obj, attr.key, None)
        if v is None:
            continue
        name = f"{mapper.local_table.name}.{attr.key}"
        if isinstance(col.type, String) and col.type.length and isinstance(v, str) and len(v) > col.type.length:
            out.append(f"{name}: 최대 {col.type.length}자 (입력 {len(v)}자)")
        elif isinstance(col.type, JSON) and _json_has_bad_number(v):
            out.append(f"{name}: 숫자가 아닌 값(NaN·무한대)")
        elif _bad_number(v):
            out.append(f"{name}: 숫자가 아닌 값(NaN·무한대)")
    return out


@event.listens_for(Session, "before_flush")
def _check_values(session: Session, _ctx, _instances):
    found = []
    for obj in list(session.new) + list(session.dirty):
        found += problems(obj)
    if found:
        raise Invalid("저장할 수 없는 값이 있습니다.", found)
