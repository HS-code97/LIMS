"""배포 전 점검: 테스트 격리, 의존성 선언, 비밀키·시드 계정, 첨부 내려받기, 감사 로그."""
import ast
import io
import json
import re
import secrets
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import config
from app.db import Base, SessionLocal
from app.main import app
from app.models import AuditLog, MasterCode, Material, ProcessPreset, User
from scripts.seed import SeedError, check_demo_allowed, seed

LIMS_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = LIMS_DIR.parent


def test_test_paths_isolated():
    """테스트는 저장소 var/·운영 파일 폴더가 아닌 임시 폴더만 씁니다."""
    for d in (config.VAR_DIR, config.FILES_DIR, config.TMP_DIR):
        assert LIMS_DIR not in d.resolve().parents, d
    assert config.FILES_DIR.resolve().parent == config.VAR_DIR.resolve()
    assert config.DATABASE_URL.startswith("sqlite") or "test" in config.DATABASE_URL


# import 이름 ≠ 배포 패키지 이름 (starlette는 fastapi가 함께 설치)
DIST_NAME = {"PIL": "pillow", "pptx": "python-pptx", "multipart": "python-multipart", "starlette": "fastapi"}


def test_requirements_cover_imports():
    """app·scripts·alembic이 import하는 서드파티 패키지가 모두 requirements.txt에 있어야 합니다."""
    declared = set()
    for line in (REPO_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            declared.add(re.split(r"[<>=!~\[;\s]", line)[0].lower())
    local = {"app", "scripts"}
    missing = set()
    for folder in ("app", "scripts", "alembic"):
        for py in (LIMS_DIR / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for n in names:
                    top = n.split(".")[0]
                    if top in sys.stdlib_module_names or top in local or top == "__future__":
                        continue
                    if DIST_NAME.get(top, top).lower() not in declared:
                        missing.add(f"{top} ({py.relative_to(LIMS_DIR)})")
    assert not missing, sorted(missing)


PG_URL = "postgresql+psycopg://lims:pw@localhost:5432/lims"


@pytest.mark.parametrize("key", ["", "dev-only-change-me", "change-me-to-a-long-random-string", "short-key"])
def test_secret_key_rejected_on_postgres(key):
    with pytest.raises(RuntimeError):
        config.session_secret(PG_URL, key)


@pytest.fixture
def fresh_db(tmp_path):
    """빈 DB (공용 테스트 DB와 별개)."""
    eng = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


def test_seed_prod_needs_admin(fresh_db):
    with pytest.raises(SeedError):
        seed(fresh_db)


@pytest.mark.parametrize("pw", ["short", "lims1234", "admin1234"])
def test_seed_prod_rejects_weak_admin_password(fresh_db, pw):
    with pytest.raises(SeedError):
        seed(fresh_db, admin=("boss", pw))


def test_seed_prod_creates_only_given_admin(fresh_db):
    seed(fresh_db, admin=("boss", "a-long-admin-pw"))
    users = {u.emp_no: u for u in fresh_db.scalars(select(User))}
    assert set(users) == {"boss"} and users["boss"].role == "ADMIN"
    owners = set(fresh_db.scalars(select(ProcessPreset.owner_id)))
    assert owners == {users["boss"].id}
    seed(fresh_db)          # 다시 실행: 기존 관리자를 쓰고 계정을 더 만들지 않음
    assert fresh_db.scalar(select(func.count()).select_from(User)) == 1


def test_seed_demo_only_on_sqlite():
    check_demo_allowed("sqlite")
    with pytest.raises(SeedError):
        check_demo_allowed("postgresql")


@pytest.fixture(scope="module")
def kim():
    """일반 사용자(USER) 세션. conftest의 current_user_id 설정 없이 HTTP 경로만 탑니다."""
    with TestClient(app) as c:
        r = c.post("/login", data={"emp_no": "kim", "password": "lims1234"}, follow_redirects=False)
        assert r.status_code == 303
        yield c


def _upload(client, name: str, body: bytes) -> int:
    r = client.post("/api/files", files={"files": (name, body)})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["attachment_id"]


@pytest.mark.parametrize("name, body", [
    ("evil.html", b"<script>alert(document.cookie)</script>"),
    ("evil.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("note.xml", b"<a/>"),
])
def test_download_unsafe_types_as_attachment(kim, name, body):
    r = kim.get(f"/files/{_upload(kim, name, body)}")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_download_image_inline_sandboxed(kim):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    att_id = _upload(kim, "photo.png", buf.getvalue())
    r = kim.get(f"/files/{att_id}")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert kim.get(f"/files/{att_id}?dl=1").headers["content-disposition"].startswith("attachment")


def _audits_after(last_id: int) -> list[AuditLog]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.id > last_id).order_by(AuditLog.id)))


def _last_audit_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.max(AuditLog.id))) or 0


def _uid(emp_no: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.emp_no == emp_no))


def test_audit_http_insert_and_delete(kim):
    """웹 요청의 변경도 사용자와 행 번호가 남아야 합니다(INSERT·논리 삭제)."""
    last = _last_audit_id()
    r = kim.post("/admin/materials", data={"coil_no": "AUDIT-COIL-1", "steel_grade": "SPCC"}, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        mat_id = db.scalar(select(Material.id).where(Material.coil_no == "AUDIT-COIL-1"))
    ins = [a for a in _audits_after(last) if a.table_name == "materials"]
    assert [(a.action, a.row_id, a.user_id) for a in ins] == [("INSERT", mat_id, _uid("kim"))]

    att_id = _upload(kim, "audit_note.txt", b"audit")
    last = _last_audit_id()
    assert kim.delete(f"/api/files/{att_id}").status_code == 200
    dels = [a for a in _audits_after(last) if a.table_name == "attachments"]
    assert [(a.action, a.row_id, a.user_id) for a in dels] == [("DELETE", att_id, _uid("kim"))]


def test_audit_http_update_composite_key():
    """복합키 테이블(master_codes) 수정은 row_id 대신 _pk로 어느 행인지 남깁니다."""
    with SessionLocal() as db:
        z4 = db.get(MasterCode, ("BATH", "Z4"))
        name, spec = z4.name, json.dumps(z4.spec) if z4.spec else ""
    with TestClient(app) as hhs:
        assert hhs.post("/login", data={"emp_no": "hhs", "password": "lims1234"},
                        follow_redirects=False).status_code == 303
        last = _last_audit_id()
        r = hhs.post("/admin/codes", data={"category": "BATH", "code": "Z4", "name": name, "spec": spec,
                                           "description": "audit-test"}, follow_redirects=False)
        assert r.status_code == 303
    ups = [a for a in _audits_after(last) if a.table_name == "master_codes"]
    assert len(ups) == 1 and ups[0].action == "UPDATE" and ups[0].user_id == _uid("hhs")
    assert ups[0].after["_pk"] == ["BATH", "Z4"] and ups[0].after["description"] == "audit-test"


def test_secret_key_accepted():
    good = secrets.token_urlsafe(48)
    assert config.session_secret(PG_URL, good) == good
    assert config.session_secret("sqlite:///x.db", "") == config.DEV_SECRET_KEY
