"""테스트용 임시 DB·파일 폴더. app import 전에 환경변수를 설정합니다."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="lims_test_"))
os.environ["LIMS_VAR_DIR"] = str(_tmp)
# 회사 컨테이너에서 PostgreSQL로 돌릴 때: LIMS_TEST_DATABASE_URL=postgresql+psycopg://lims:...@localhost/lims_test
# (빈 테스트 전용 DB를 쓰세요. 테스트가 스키마를 만들고 데이터를 넣습니다.)
os.environ["LIMS_DATABASE_URL"] = os.getenv("LIMS_TEST_DATABASE_URL") or f"sqlite:///{(_tmp / 'test.db').as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.db import Base, SessionLocal, current_user_id, engine  # noqa: E402
from scripts.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db, demo=True)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def user_id(db):
    from sqlalchemy import select
    from app.models import User
    uid = db.scalar(select(User.id).where(User.emp_no == "hhs"))
    current_user_id.set(uid)
    return uid
