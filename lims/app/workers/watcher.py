"""장비 PC 폴더 감시 (7장 P5 2단계 확장).

장비 PC(Windows)와 서버 사이 공유 폴더를 주기적으로 훑어, 크기가 안정된 새 파일을 업로드와 같은
파이프라인(파일명 매칭 → 해시 중복 검사 → 저장·썸네일 → 미분류함)에 넣습니다. 원본 파일은 건드리지 않습니다.

환경변수
  LIMS_WATCH_DIRS     감시 폴더, ';'로 구분 (예: /mnt/sem;/mnt/xrd)   ← 11.3 확인 필요(공유 경로)
  LIMS_WATCH_USER     미분류 파일을 받을 사번 (기본 admin)
  LIMS_WATCH_INTERVAL 주기(초, 기본 60) · LIMS_WATCH_STABLE 크기 안정 대기(초, 기본 10)
  LIMS_WATCH_EXT      대상 확장자 (기본 jpg,jpeg,png,tif,tiff,bmp,csv,txt,xlsx,pdf,raw,dat)
실행:  python -m app.workers.watcher [--once]
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from ..config import TMP_DIR, VAR_DIR
from ..db import SessionLocal, current_user_id
from ..models import User
from ..services import file_ingest

log = logging.getLogger("lims.watcher")
STATE = VAR_DIR / "watcher_state.json"


def _cfg():
    dirs = [Path(p) for p in os.getenv("LIMS_WATCH_DIRS", "").split(";") if p.strip()]
    exts = {"." + e.strip().lower() for e in os.getenv(
        "LIMS_WATCH_EXT", "jpg,jpeg,png,tif,tiff,bmp,csv,txt,xlsx,pdf,raw,dat").split(",")}
    return dirs, exts, os.getenv("LIMS_WATCH_USER", "admin"), int(os.getenv("LIMS_WATCH_INTERVAL", "60")), \
        int(os.getenv("LIMS_WATCH_STABLE", "10"))


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def scan_once(dirs: list[Path], exts: set[str], emp_no: str, stable: int, state: dict) -> list[dict]:
    """한 번 훑기. state: {경로: "크기:mtime"} — 처리한 파일은 다시 넣지 않습니다."""
    out = []
    now = time.time()
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.emp_no == emp_no))
        current_user_id.set(uid)
        for d in dirs:
            if not d.is_dir():
                log.warning("감시 폴더 없음: %s", d)
                continue
            for p in sorted(d.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in exts or p.name.startswith((".", "~$")):
                    continue
                st = p.stat()
                sig = f"{st.st_size}:{int(st.st_mtime)}"
                key = str(p)
                if state.get(key) == sig or now - st.st_mtime < stable:
                    continue
                tmp = TMP_DIR / f"{uuid.uuid4().hex}.part"
                shutil.copy2(p, tmp)
                r = file_ingest.ingest(db, tmp, p.name, user_id=uid, source="watcher", auto_test_run=True)
                db.commit()
                state[key] = sig
                out.append(r.as_dict() | {"path": key})
                log.info("%s → %s %s", p.name, r.status, r.short_id or "")
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dirs, exts, emp_no, interval, stable = _cfg()
    if not dirs:
        log.error("LIMS_WATCH_DIRS가 비어 있습니다.")
        sys.exit(2)
    state = _load_state()
    while True:
        try:
            scan_once(dirs, exts, emp_no, stable, state)
        except Exception:  # 한 번 실패해도 감시는 계속
            log.exception("scan 실패")
        if "--once" in sys.argv:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
