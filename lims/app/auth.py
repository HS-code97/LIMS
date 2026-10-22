"""로그인·세션·권한 (8장 운영 규칙: 누구나 조회, 수정은 작성자·소유자·ADMIN, 결과 추가는 누구나)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import current_user_id, get_db
from .models import ApiKey, User

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


# ── 장비·외부 앱 API 키 ─────────────────────────────────────────────
API_KEY_HEADER = "X-API-Key"
# 키의 scope별로 부를 수 있는 엔드포인트 ("모듈.함수"). 그 밖의 주소는 키로 부를 수 없습니다.
API_SCOPES = {
    "pv": {"app.routers.analysis.receive_pv"},          # HMI PV 실행기록 CSV (6.5절)
    "xcut": {"app.routers.analysis.xcut_import"},       # X-cut 블리스터 앱 결과
    "files": {"app.routers.files.upload"},              # 장비 PC 파일 업로드
}


def new_api_key() -> str:
    return "lims_" + secrets.token_urlsafe(32)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _api_key_user(request: Request, db: Session, raw: str) -> User:
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw), ApiKey.is_active.is_(True)))
    if key is None or not key.user.is_active:
        raise HTTPException(401, "API 키가 올바르지 않거나 중지되었습니다.")
    ep = request.scope.get("endpoint")
    allowed = {e for s in (key.scopes or []) for e in API_SCOPES.get(s, ())}
    if ep is None or f"{ep.__module__}.{ep.__name__}" not in allowed:
        raise HTTPException(403, f"API 키 '{key.name}'로는 이 주소를 부를 수 없습니다 (범위: {', '.join(key.scopes or [])}).")
    now = datetime.now()
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=5):
        # 감사 로그에 남길 일이 아니라 ORM 밖에서 바로 갱신
        db.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        db.commit()
    request.state.api_key = key.name
    return key.user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None and (raw := request.headers.get(API_KEY_HEADER)):
        user = _api_key_user(request, db, raw)
    if user is not None and not user.is_active:
        user = None
    # 감사 로그용 사용자. sync 의존성은 스레드풀에서 돌아 contextvar가 엔드포인트까지 전달되지 않으므로,
    # 같은 요청의 엔드포인트와 공유되는 세션(get_db는 요청마다 캐시)에 함께 적어 둡니다.
    db.info["user_id"] = user.id if user else None
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
