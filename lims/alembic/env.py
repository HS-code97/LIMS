"""Alembic 환경: 모델 메타데이터와 앱 설정의 DB URL을 씁니다."""
import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=engine.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as conn:
        sqlite = conn.dialect.name == "sqlite"
        if sqlite:
            # SQLite batch 모드는 표를 새로 만들어 옮기므로, 다른 표가 참조 중이면 외래키 검사가 막습니다.
            # 트랜잭션 밖에서만 바꿀 수 있어 시작 전에 끄고, 끝나면 foreign_key_check로 깨진 참조가 없는지 확인합니다.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=sqlite, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"마이그레이션 후 외래키가 깨졌습니다: {broken[:5]}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
