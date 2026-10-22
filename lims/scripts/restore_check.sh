#!/usr/bin/env bash
# 복원 연습 (월 1회 권장): 최신 DB 덤프를 임시 DB에 복원해 주요 테이블 행 수를 보여 주고 지웁니다.
# 운영 DB는 건드리지 않습니다. DB 사용자에게 CREATEDB 권한이 필요합니다.
#   /opt/lims/lims/scripts/restore_check.sh            (기본 덤프 폴더의 최신 덤프)
#   /opt/lims/lims/scripts/restore_check.sh 파일.dump  (지정한 덤프)
set -euo pipefail

ENV_FILE="${LIMS_ENV_FILE:-/opt/lims/.env}"
env_get() { [[ -f "$ENV_FILE" ]] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 || true; }

DB_NAME="${LIMS_DB_NAME:-lims}"
CHECK_DB="${LIMS_RESTORE_CHECK_DB:-lims_restore_check}"
DUMP_DIR="${LIMS_DUMP_DIR:-/data/backup/db}"
export PGHOST="${PGHOST:-localhost}" PGUSER="${PGUSER:-lims}"
export PGPASSWORD="${PGPASSWORD:-${LIMS_DB_PASSWORD:-$(env_get LIMS_DB_PASSWORD)}}"

[[ "$CHECK_DB" != "$DB_NAME" ]] || { echo "복원 대상이 운영 DB와 같습니다: $CHECK_DB" >&2; exit 1; }
dump="${1:-$(ls -1t "$DUMP_DIR"/lims_*.dump 2>/dev/null | head -n 1)}"
[[ -n "$dump" && -s "$dump" ]] || { echo "덤프가 없습니다: ${dump:-$DUMP_DIR}" >&2; exit 1; }

echo "복원 연습: $dump → $CHECK_DB"
dropdb --if-exists "$CHECK_DB"
createdb "$CHECK_DB"
trap 'dropdb --if-exists "$CHECK_DB"' EXIT
pg_restore --no-owner --exit-on-error -d "$CHECK_DB" "$dump"
psql -d "$CHECK_DB" -v ON_ERROR_STOP=1 -At -F $'\t' -c "
  SELECT 'alembic', version_num FROM alembic_version
  UNION ALL SELECT 'process_runs', count(*)::text FROM process_runs
  UNION ALL SELECT 'specimens', count(*)::text FROM specimens
  UNION ALL SELECT 'test_results', count(*)::text FROM test_results
  UNION ALL SELECT 'attachments', count(*)::text FROM attachments
  UNION ALL SELECT 'audit_log', count(*)::text FROM audit_log"
echo "복원 연습 성공 (임시 DB는 지웁니다)"
