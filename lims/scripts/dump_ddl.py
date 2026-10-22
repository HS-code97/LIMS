"""모델 → PostgreSQL DDL (db/schema_postgres.sql). 설계서 8장 DDL과 대조용·DBA 검토용.

사용:  python -m scripts.dump_ddl
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base  # noqa: E402

out = ["-- 도금강판 R&D LIMS v2.3 — PostgreSQL 15+ DDL (app/models에서 자동 생성, 직접 고치지 마세요)",
       "-- 운영 적용은 Alembic(alembic upgrade head)을 쓰고, 이 파일은 검토·대조용입니다.", ""]
d = postgresql.dialect()
for t in Base.metadata.sorted_tables:
    out.append(str(CreateTable(t).compile(dialect=d)).strip() + ";")
    for ix in sorted(t.indexes, key=lambda i: i.name):
        out.append(str(CreateIndex(ix).compile(dialect=d)).strip() + ";")
    out.append("")
out.append("-- serial_no 형식 (PostgreSQL 전용 정규식 검사)")
out.append("ALTER TABLE specimens ADD CONSTRAINT ck_serial_digits CHECK (serial_no ~ '^[0-9]{4}$');")
path = Path(__file__).resolve().parent.parent / "db" / "schema_postgres.sql"
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(path)
