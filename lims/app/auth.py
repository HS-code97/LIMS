"""로그인·세션·권한 (8장 운영 규칙: 누구나 조회, 수정은 작성자·소유자·ADMIN, 결과 추가는 누구나)."""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import current_user_id, get_db
from .models import User

ITER = 240_000


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2_sha256${ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except ValueError:
        return False


class LoginRequired(Exception):
    pass


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is not None and not user.is_active:
        user = None
    current_user_id.set(user.id if user else None)
    request.state.user = user
    return user


def require_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "관리자만 할 수 있습니다.")
    return user


def can_edit(user: User, *owner_ids: int | None) -> bool:
    return user.is_admin or any(o == user.id for o in owner_ids if o is not None)


def ensure_can_edit(user: User, *owner_ids: int | None) -> None:
    if not can_edit(user, *owner_ids):
        raise HTTPException(403, "작성자·시편 소유자·관리자만 수정할 수 있습니다.")
