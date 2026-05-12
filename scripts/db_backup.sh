#!/usr/bin/env bash
# Production Postgres backup for university-helper
# Usage: bash scripts/db_backup.sh [backup_dir]
# Cron example (run on VPS): 15 3 * * * /opt/university-helper/scripts/db_backup.sh >> /var/log/uh-backup.log 2>&1
set -euo pipefail

BACKUP_DIR="${1:-/opt/backups/university-helper}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
CONTAINER="${BACKUP_CONTAINER:-shuake-easy-learning-db}"
STAMP="$(date +%F-%H%M)"

mkdir -p "$BACKUP_DIR"

OUT="$BACKUP_DIR/uh-$STAMP.sql.gz"
echo "[$(date -Iseconds)] backing up $CONTAINER -> $OUT"
docker exec "$CONTAINER" pg_dumpall -U "${POSTGRES_USER:-easylearning}" | gzip > "$OUT"
SIZE=$(du -h "$OUT" | cut -f1)
echo "[$(date -Iseconds)] backup ok ($SIZE)"

# Also snapshot the prod .env (contains real SECRET_KEY / POSTGRES_PASSWORD)
ENV_PATH="${ENV_PATH:-/opt/university-helper/.env}"
if [ -f "$ENV_PATH" ]; then
  cp "$ENV_PATH" "$BACKUP_DIR/.env.$STAMP"
  echo "[$(date -Iseconds)] env snapshotted"
fi

# Retention
find "$BACKUP_DIR" -name "uh-*.sql.gz" -mtime +"$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name ".env.*" -mtime +"$RETAIN_DAYS" -delete
echo "[$(date -Iseconds)] retention pruned (>$RETAIN_DAYS days)"
