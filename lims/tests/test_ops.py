"""3단계 회귀 테스트: 운영 (폴더 감시 장애 격리·크기 안정 판정, 수집 실패 시 고아 파일 정리,
Alembic 마이그레이션 = 모델)."""
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import FILES_DIR, TMP_DIR
from app.services import file_ingest
from app.workers import watcher

LIMS_DIR = Path(__file__).resolve().parent.parent
TXT = {".txt"}


def _write(p: Path, age: float = 0) -> Path:
    p.write_text(uuid.uuid4().hex)                    # 내용이 매번 달라야 해시 중복으로 빠지지 않음
    if age:
        t = time.time() - age
        os.utime(p, (t, t))
    return p


def test_watcher_one_bad_file_does_not_stop_scan(tmp_path, monkeypatch):
    d = tmp_path / "eq"
    d.mkdir()
    bad, good = _write(d / "a_locked.txt"), _write(d / "b_ok.txt")
    real_copy = watcher.shutil.copy2

    def copy2(src, dst, *a, **kw):
        if Path(src).name == bad.name:
            raise PermissionError("장비 PC가 파일을 잡고 있음")
        return real_copy(src, dst, *a, **kw)

    monkeypatch.setattr(watcher.shutil, "copy2", copy2)
    state = {}
    out = watcher.scan_once([d], TXT, "hhs", stable=0, state=state)
    assert [Path(o["path"]).name for o in out] == ["b_ok.txt"]
    assert str(bad) not in state and str(good) in state
    assert not list(TMP_DIR.glob("*.part"))                     # 실패한 복사본이 남지 않음
    monkeypatch.undo()
    out = watcher.scan_once([d], TXT, "hhs", stable=0, state=state)   # 잠금이 풀리면 다음 훑기에서 처리
    assert [Path(o["path"]).name for o in out] == ["a_locked.txt"]


def test_watcher_waits_until_size_is_stable(tmp_path):
    d = tmp_path / "eq2"
    d.mkdir()
    f = _write(d / "growing.txt", age=30)
    state, pending = {}, {}
    assert watcher.scan_once([d], TXT, "hhs", stable=5, state=state, pending=pending) == []   # 처음 본 파일
    with open(f, "a") as fh:                                     # 장비가 아직 쓰는 중
        fh.write("more")
    t = time.time() - 30
    os.utime(f, (t, t + 1))
    assert watcher.scan_once([d], TXT, "hhs", stable=5, state=state, pending=pending) == []   # 크기가 바뀜
    out = watcher.scan_once([d], TXT, "hhs", stable=5, state=state, pending=pending)          # 그대로면 처리
    assert [o["status"] for o in out] == ["unmatched"]


def test_ingest_removes_files_when_db_insert_fails(db, monkeypatch):
    """업로드와 감시가 같은 파일을 동시에 넣어 해시 UNIQUE 위반이 나도 디스크에 고아 파일이 남지 않음."""
    name = f"race_{uuid.uuid4().hex[:8]}.txt"
    tmp = TMP_DIR / f"{uuid.uuid4().hex}.part"
    tmp.write_text(uuid.uuid4().hex)

    def flush(*_a, **_kw):
        raise IntegrityError("INSERT INTO attachments", {}, Exception("UNIQUE constraint failed: attachments.sha256"))

    monkeypatch.setattr(db, "flush", flush)
    with pytest.raises(IntegrityError):
        file_ingest.ingest(db, tmp, name, user_id=None)
    assert not tmp.exists()
    assert not list(FILES_DIR.rglob(f"*_{name}"))


def test_alembic_head_matches_models(tmp_path):
    """마이그레이션을 끝까지 올린 빈 DB가 모델과 같아야 합니다(모델만 고치고 마이그레이션을 빠뜨리면 실패)."""
    env = {**os.environ, "LIMS_VAR_DIR": str(tmp_path), "LIMS_DATABASE_URL": f"sqlite:///{(tmp_path / 'm.db').as_posix()}",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    for args in (["upgrade", "head"], ["check"]):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=LIMS_DIR, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, (args, r.stdout, r.stderr)
    assert "No new upgrade operations" in r.stdout + r.stderr
