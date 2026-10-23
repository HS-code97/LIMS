"""PostgreSQL 방언 검사 (서버 없이): DDL·주요 질의가 PostgreSQL SQL로 컴파일되는지.
실제 PostgreSQL 실행은 LIMS_TEST_DATABASE_URL을 주고 전체 테스트를 돌립니다(conftest 참조)."""
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import Base
from app.services import lineage, search

PG = postgresql.dialect()


def sql(stmt) -> str:
    return str(stmt.compile(dialect=PG))


def test_ddl_postgres():
    out = "\n".join(str(CreateTable(t).compile(dialect=PG)) for t in Base.metadata.sorted_tables)
    idx = "\n".join(str(CreateIndex(i).compile(dialect=PG)) for t in Base.metadata.sorted_tables for i in t.indexes)
    assert "short_id VARCHAR(16) NOT NULL" in out and "UNIQUE (short_id)" in out          # 각인번호 = 유일키
    assert "CONSTRAINT ck_stage CHECK (stage IN ('A','B','C','D','E'))" in out
    assert "UNIQUE (coil_code)" in out
    assert out.count("JSONB") >= 16 and "BIGSERIAL" in out
    assert "USING gin (recipe)" in idx and "USING gin (metrics)" in idx
    assert "WHERE NOT is_deleted" in idx and "WHERE specimen_id IS NULL" in idx
    assert "ON DELETE RESTRICT" in out and "CASCADE" not in out           # D-20


def test_queries_postgres():
    q = sql(lineage.descendants_stmt(1))
    assert "WITH RECURSIVE" in q
    qy = search.Query(q="QV3-A6-C-102-M206K", project="A6", stage="C", test_type="CCT", code="M2", basis="actual",
                      params=[search.ParamFilter("out.cw_top", 50, 55), search.ParamFilter("rth.DP", None, -30)])
    s = sql(search.build(qy))
    assert s.count("JOIN effective_params AS") == 2 and "LIMIT" in s and "LIKE" in s
