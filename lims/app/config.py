"""경로·DB URL·업로드 한도 (환경변수로 덮어쓰기)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # lims/
APP_DIR = BASE_DIR / "app"
SEED_DIR = BASE_DIR / "data" / "seed"
VAR_DIR = Path(os.getenv("LIMS_VAR_DIR", BASE_DIR / "var"))

# 운영: postgresql+psycopg://lims:***@localhost:5432/lims
# 개발: SQLite 파일 (JSONB 대신 JSON, 나머지 스키마는 동일)
DATABASE_URL = os.getenv("LIMS_DATABASE_URL", f"sqlite:///{(VAR_DIR / 'lims.db').as_posix()}")
FILES_DIR = Path(os.getenv("LIMS_FILES_DIR", VAR_DIR / "files"))   # 운영: /data/lims/files
TMP_DIR = Path(os.getenv("LIMS_TMP_DIR", VAR_DIR / "tmp"))
SECRET_KEY = os.getenv("LIMS_SECRET_KEY", "")
DEV_SECRET_KEY = "dev-only-change-me"
# 예시 파일·옛 기본값 그대로의 키는 공개된 값이라 세션 쿠키 위조에 쓰일 수 있습니다.
_KNOWN_SECRET_KEYS = {DEV_SECRET_KEY, "change-me-to-a-long-random-string"}
MAX_UPLOAD_MB = int(os.getenv("LIMS_MAX_UPLOAD_MB", "200"))
THUMB_SIZES = (400, 1600)

# 같은 키에 여러 경로의 실측이 있을 때 대표값 출처 순위 (6.8절, 설정값)
SOURCE_PRIORITY = os.getenv("LIMS_SOURCE_PRIORITY", "test,lab,manual,pv").split(",")

# ── 11.3 확인 필요 사항: 사내 확인 후 환경변수로 넣습니다 (관리 > 시스템 설정에서 현재 값 확인) ──
PORT = int(os.getenv("LIMS_PORT", "8610"))                                   # 외부 접속 포트 (IT)
BACKUP_TARGET = os.getenv("LIMS_BACKUP_TARGET", "")                          # 컨테이너 밖 백업 경로
WATCH_DIRS = os.getenv("LIMS_WATCH_DIRS", "")                                # 장비 PC 공유 폴더
PPT_TEMPLATE = os.getenv("LIMS_PPT_TEMPLATE", "")                            # 회사 표준 A4 가로 .pptx
# 레이저 각인기 CSV 형식
ENGRAVE_COLUMNS = os.getenv("LIMS_ENGRAVE_COLUMNS", "short_id,display_id,datamatrix_text").split(",")
ENGRAVE_DELIMITER = os.getenv("LIMS_ENGRAVE_DELIMITER", ",").replace("\\t", "\t")
ENGRAVE_ENCODING = os.getenv("LIMS_ENGRAVE_ENCODING", "utf-8-sig")           # 장비가 ANSI면 cp949
ENGRAVE_HEADER = os.getenv("LIMS_ENGRAVE_HEADER", "1") == "1"
# 라벨프린터
LABEL_SIZE_MM = tuple(float(x) for x in os.getenv("LIMS_LABEL_SIZE_MM", "50x20").lower().split("x"))
LABEL_CODE = os.getenv("LIMS_LABEL_CODE", "datamatrix")                      # datamatrix / qr

for d in (VAR_DIR, FILES_DIR, TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)


def session_secret(db_url: str = DATABASE_URL, key: str = SECRET_KEY) -> str:
    """세션 서명 키. 개발용 SQLite만 기본 키를 허용하고, 운영 DB에서는 안전한 키가 없으면 기동을 막습니다."""
    if db_url.startswith("sqlite"):
        if not key:
            logging.getLogger("lims").warning("LIMS_SECRET_KEY 미설정 — 개발용 기본 키로 세션을 서명합니다.")
        return key or DEV_SECRET_KEY
    if not key or key in _KNOWN_SECRET_KEYS or len(key) < 32:
        raise RuntimeError(
            "LIMS_SECRET_KEY가 없거나 안전하지 않습니다(32자 이상, 예시 값 금지). "
            "생성: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    return key
