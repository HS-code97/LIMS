#!/usr/bin/env bash
# LIMS 백업 (설계서 7장 P8) — cron 매일 02:00
#   0 2 * * * /opt/lims/scripts/backup.sh >> /data/backup/backup.log 2>&1
# BACKUP_TARGET: 컨테이너 밖 사내 NAS·백업 서버 경로 (11.3 확인 필요 사항)
set -euo pipefail
DB_NAME="${LIMS_DB_NAME:-lims}"
FILES_DIR="${LIMS_FILES_DIR:-/data/lims/files}"
DUMP_DIR="${LIMS_DUMP_DIR:-/data/backup/db}"
BACKUP_TARGET="${LIMS_BACKUP_TARGET:-}"

mkdir -p "$DUMP_DIR"
echo "[$(date '+%F %T')] backup start"
pg_dump -Fc "$DB_NAME" > "$DUMP_DIR/lims_$(date +%F).dump"
find "$DUMP_DIR" -name 'lims_*.dump' -mtime +30 -delete          # 컨테이너 안 30일 보관
if [[ -n "$BACKUP_TARGET" ]]; then
  rsync -a --delete "$FILES_DIR/" "$BACKUP_TARGET/files/"         # 원본 파일 복제
  rsync -a "$DUMP_DIR/" "$BACKUP_TARGET/db/"                       # DB 덤프 복제
else
  echo "WARN: LIMS_BACKUP_TARGET 미설정 — 컨테이너 밖 복제를 건너뜀"
fi
echo "[$(date '+%F %T')] backup done"
