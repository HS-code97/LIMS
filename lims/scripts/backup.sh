#!/usr/bin/env bash
# LIMS 백업 (설계서 7장 P8) — cron 매일 02:00
#   0 2 * * * /opt/lims/lims/scripts/backup.sh >> /data/backup/backup.log 2>&1
#
# 안전 장치
# - cron은 .env를 읽지 않으므로 필요한 값만 .env에서 직접 읽습니다(.env는 ';' 등 때문에 source하지 않음).
# - 외부 백업 위치(LIMS_BACKUP_TARGET)가 없으면 실패(exit 1)합니다. 의도적으로 컨테이너 안에만 둘 때는
#   LIMS_BACKUP_LOCAL_ONLY=1.
# - 덤프는 임시 이름으로 받아 pg_restore --list로 읽히는지 확인한 뒤에만 이름을 붙입니다(실패한 0바이트 덤프가
#   정상 덤프를 덮거나 대신하지 않음). 이름에 시각이 들어가 같은 날 다시 돌려도 덮어쓰지 않습니다.
# - 보관 정리는 30일 지난 덤프만, 그리고 최신 7개는 항상 남깁니다.
# - 원본 파일 복제는 원본 폴더가 비어 있으면(마운트 누락 등) 중단하고, 지워지거나 바뀐 파일은 지우지 않고
#   files-changed/{시각}/로 옮겨 둡니다(rsync --backup). 랜섬웨어·실수로 원본이 망가져도 이전 본이 남습니다.
# 복원 연습: scripts/restore_check.sh
set -euo pipefail

ENV_FILE="${LIMS_ENV_FILE:-/opt/lims/.env}"
env_get() { [[ -f "$ENV_FILE" ]] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 || true; }

DB_NAME="${LIMS_DB_NAME:-lims}"
FILES_DIR="${LIMS_FILES_DIR:-$(env_get LIMS_FILES_DIR)}"; FILES_DIR="${FILES_DIR:-/data/lims/files}"
DUMP_DIR="${LIMS_DUMP_DIR:-/data/backup/db}"
BACKUP_TARGET="${LIMS_BACKUP_TARGET:-$(env_get LIMS_BACKUP_TARGET)}"
export PGHOST="${PGHOST:-localhost}" PGUSER="${PGUSER:-lims}"
export PGPASSWORD="${PGPASSWORD:-${LIMS_DB_PASSWORD:-$(env_get LIMS_DB_PASSWORD)}}"
STAMP="$(date +%F_%H%M%S)"

log() { echo "[$(date '+%F %T')] $*"; }
part=""
fail() { [[ -n "$part" ]] && rm -f -- "$part"; log "FAILED: $*"; exit 1; }
trap 'fail "line $LINENO: $BASH_COMMAND"' ERR

log "backup start"
if [[ -z "$BACKUP_TARGET" && "${LIMS_BACKUP_LOCAL_ONLY:-0}" != "1" ]]; then
  fail "LIMS_BACKUP_TARGET 미설정 — 컨테이너 밖 복제 없이는 백업으로 보지 않습니다 (.env 또는 LIMS_BACKUP_LOCAL_ONLY=1)"
fi

# 1. DB 덤프 → 검증 → 이름 붙이기
mkdir -p "$DUMP_DIR"
part="$DUMP_DIR/.lims_$STAMP.dump.part"
pg_dump -Fc "$DB_NAME" > "$part"
[[ -s "$part" ]] || fail "덤프가 비어 있음: $part"
pg_restore --list "$part" > /dev/null || fail "덤프를 읽을 수 없음: $part"
mv "$part" "$DUMP_DIR/lims_$STAMP.dump"
log "dump ok: lims_$STAMP.dump ($(du -h "$DUMP_DIR/lims_$STAMP.dump" | cut -f1))"

# 2. 보관 정리: 최신 7개는 남기고, 그보다 오래된 것 중 30일 지난 것만
ls -1t "$DUMP_DIR"/lims_*.dump | tail -n +8 | while read -r f; do
  if [[ -n "$(find "$f" -mtime +30)" ]]; then rm -f -- "$f"; log "pruned $(basename "$f")"; fi
done

# 3. 컨테이너 밖 복제
if [[ -n "$BACKUP_TARGET" ]]; then
  [[ -d "$FILES_DIR" ]] || fail "원본 파일 폴더 없음: $FILES_DIR"
  [[ -n "$(find "$FILES_DIR" -type f -print -quit)" ]] || fail "원본 파일 폴더가 비어 있음(마운트 확인): $FILES_DIR"
  mkdir -p "$BACKUP_TARGET/files" "$BACKUP_TARGET/db"
  rsync -a --delete --backup --backup-dir="$BACKUP_TARGET/files-changed/$STAMP" "$FILES_DIR/" "$BACKUP_TARGET/files/"
  rsync -a --exclude='.*.part' "$DUMP_DIR/" "$BACKUP_TARGET/db/"
  log "replicated to $BACKUP_TARGET"
else
  log "WARN: LIMS_BACKUP_LOCAL_ONLY=1 — 컨테이너 밖 복제를 건너뜀"
fi
date '+%F %T' > "$DUMP_DIR/last_success"
log "backup done"
