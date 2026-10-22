"""장비 PC 폴더 감시 (7장 P5 2단계 확장).

장비 PC(Windows)와 서버 사이 공유 폴더를 주기적으로 훑어, 크기가 안정된 새 파일을 업로드와 같은
파이프라인(파일명 매칭 → 해시 중복 검사 → 저장·썸네일 → 미분류함)에 넣습니다. 원본 파일은 건드리지 않습니다.

환경변수
  LIMS_WATCH_DIRS     감시 폴더, ';'로 구분 (예: /mnt/sem;/mnt/xrd)   ← 11.3 확인 필요(공유 경로)
  LIMS_WATCH_USER     미분류 파일을 받을 사번 (기본 admin)
  LIMS_WATCH_INTERVAL 주기(초, 기본 60) · LIMS_WATCH_STABLE 크기 안정 대기(초, 기본 10)
                      안정 = 마지막 수정 후 STABLE초가 지났고, 직전 훑기와 크기·수정 시각이 같음
                      (장비가 아직 쓰는 중인 파일을 반쪽으로 넣지 않도록. 0이면 바로 넣음)
파일 하나가 실패해도(잠김·읽기 오류·DB 충돌) 그 파일만 다음 훑기에서 다시 시도하고 나머지는 계속 처리합니다.
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
from ..services import param_dict as pdict

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


def _save_state(state: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE)


# 직전 훑기에서 본 미처리 파일의 "크기:mtime" (프로세스 메모리, 크기 안정 판정용)
_pending: dict[str, str] = {}


def _is_stable(key: str, sig: str, mtime: float, now: float, stable: int, pending: dict) -> bool:
    if stable <= 0:
        return True
    seen, pending[key] = pending.get(key), sig
    return seen == sig and now - mtime >= stable


def scan_once(dirs: list[Path], exts: set[str], emp_no: str, stable: int, state: dict,
              pending: dict | None = None) -> list[dict]:
    """한 번 훑기. state: {경로: "크기:mtime"} — 처리한 파일은 다시 넣지 않습니다(파일마다 저장)."""
    pending = _pending if pending is None else pending
    out = []
    now = time.time()
    with SessionLocal() as db:
        pdict.sync(db)
        uid = db.scalar(select(User.id).where(User.emp_no == emp_no))
        current_user_id.set(uid)
        for d in dirs:
            if not d.is_dir():
                log.warning("감시 폴더 없음: %s", d)
                continue
            for p in sorted(d.rglob("*")):
                try:
                    if not p.is_file() or p.suffix.lower() not in exts or p.name.startswith((".", "~$")):
                        continue
                    st = p.stat()
                except OSError:
                    continue
                sig = f"{st.st_size}:{int(st.st_mtime)}"
                key = str(p)
                if state.get(key) == sig or not _is_stable(key, sig, st.st_mtime, now, stable, pending):
                    continue
                tmp = TMP_DIR / f"{uuid.uuid4().hex}.part"
                try:
                    shutil.copy2(p, tmp)
                    r = file_ingest.ingest(db, tmp, p.name, user_id=uid, source="watcher", auto_test_run=True)
                    db.commit()
                except Exception:  # 잠긴 파일·읽기 오류·업로드와의 해시 충돌 등 — 이 파일만 다음에 다시
                    db.rollback()
                    tmp.unlink(missing_ok=True)
                    log.exception("%s 처리 실패 — 다음 훑기에서 다시 시도", p)
                    continue
                state[key] = sig
                pending.pop(key, None)
                _save_state(state)
                out.append(r.as_dict() | {"path": key})
                log.info("%s → %s %s", p.name, r.status, r.short_id or "")
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
