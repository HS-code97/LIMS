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


def test_alembic_0004_migrates_v23_numbers(tmp_path):
    """v2.3 데이터(26P4-P0101·C·S) → v3.0 각인번호(코일-가지-후절단-조각), 과제 A6, 옛 번호는 legacy_id."""
    import sqlite3
    db_file = tmp_path / "old.db"
    env = {**os.environ, "LIMS_VAR_DIR": str(tmp_path), "LIMS_DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

    def alembic(*args):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=LIMS_DIR, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, (args, r.stdout, r.stderr)

    alembic("upgrade", "0003")
    c = sqlite3.connect(db_file)
    c.executescript("""
        INSERT INTO projects (project_code, company_project_no, project_name, is_common) VALUES
            ('26P4', '2026P1234', '과제', 0), ('26X1', NULL, '탐색', 1);
        INSERT INTO materials (id, coil_no) VALUES (1, 'CQV3141');
        INSERT INTO process_runs (id, run_no, run_date, project_code, material_id, source, dict_version, recipe,
                                  base_condition_code) VALUES (1, 'PR-26-0001', '2026-10-21', '26P4', 1, 'manual', 'v', '{}', 'M206K');
        INSERT INTO specimens (id, project_code, stage, serial_no, engraved_label, parent_id, process_run_id, material_id,
                               condition_code, status, is_deleted) VALUES
            (1, '26P4', 'P', '0101', 'M206K-26P4-P0101', NULL, 1, 1, 'M206K', 'AVAILABLE', 0),
            (2, '26P4', 'P', '0102', 'M206K-26P4-P0102', NULL, 1, 1, 'M206K', 'AVAILABLE', 0),
            (3, '26P4', 'C', '0102', 'M206K-26P4-C0102', 2, 1, 1, 'M206K', 'AVAILABLE', 0),
            (4, '26P4', 'S', '0102', 'M206K-26P4-S0102', 3, 1, 1, 'M206K', 'AVAILABLE', 0),
            (5, '26P4', 'S', '0101', 'M206K-26P4-S0101', 1, 1, 1, 'M206K', 'AVAILABLE', 0),
            (6, '26X1', 'C', '0001', NULL, NULL, NULL, NULL, NULL, 'AVAILABLE', 0);
    """)
    c.commit()
    c.close()
    alembic("upgrade", "head")
    alembic("check")
    c = sqlite3.connect(db_file)
    rows = dict((r[0], r[1:]) for r in c.execute(
        "SELECT legacy_id, short_id, project_code, stage, is_panel FROM specimens"))
    assert rows["26P4-P0101"] == ("QV3-101", "A6", "C", 1)
    assert rows["26P4-P0102"] == ("QV3-102", "A6", "C", 1)
    assert rows["26P4-C0102"] == ("QV3-102-01", "A6", "C", 0)
    assert rows["26P4-S0102"] == ("QV3-102-01-1", "A6", "C", 0)
    assert rows["26P4-S0101"] == ("QV3-101-01", "A6", "C", 0)
    assert rows["26X1-C0001"][1:] == ("Y6", "B", 0)                      # 코일 없던 시편 → '이관-26X1' 코일
    assert {r[0] for r in c.execute("SELECT project_code FROM projects")} == {"A6", "Y6"}
    assert c.execute("SELECT coil_code FROM materials WHERE coil_no = 'CQV3141'").fetchone() == ("QV3",)
    assert c.execute("SELECT count(*) FROM specimen_events WHERE event_type = 'NOTE'").fetchone() == (6,)
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
