#!/usr/bin/env bash
# Production Postgres backup for university-helper.
#
# Two-channel hardening over the previous version:
#  1. Dumps are encrypted with `age` when AGE_RECIPIENT (or AGE_RECIPIENT_FILE)
#     is set — the resulting .sql.gz.age can be safely copied to remote storage.
#  2. The .env snapshot is encrypted the same way and NEVER copied in plaintext
#     when a recipient is configured.
#
# Usage:
#   AGE_RECIPIENT=age1... bash scripts/db_backup.sh [backup_dir]
#   AGE_RECIPIENT_FILE=/etc/uh/age-recipients.txt bash scripts/db_backup.sh
#
# If neither variable is set the script still runs (compatibility), but emits
# a loud warning. Set ALLOW_UNENCRYPTED=1 to silence the warning explicitly.
#
# Cron example: 15 3 * * * AGE_RECIPIENT=age1... /opt/university-helper/scripts/db_backup.sh >> /var/log/uh-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${1:-/opt/backups/university-helper}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
CONTAINER="${BACKUP_CONTAINER:-shuake-easy-learning-db}"
STAMP="$(date +%F-%H%M)"
LOG_PREFIX="[$(date -Iseconds)]"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

age_args=()
encryption="disabled"
if [[ -n "${AGE_RECIPIENT:-}" ]]; then
    age_args+=(-r "$AGE_RECIPIENT")
    encryption="recipient"
elif [[ -n "${AGE_RECIPIENT_FILE:-}" ]]; then
    age_args+=(-R "$AGE_RECIPIENT_FILE")
    encryption="recipient-file"
fi

run_age() {
    # stdin -> ciphertext on stdout
    if [[ -z "${age_args[*]:-}" ]]; then
        echo "$LOG_PREFIX ERROR: run_age called without recipients" >&2
        return 1
    fi
    age "${age_args[@]}"
}

# Keep the in-progress output separate from the published backup.  A failed
# producer in a pipe can still leave bytes in its downstream output, so the
# final filename must not be opened until every producer has succeeded and
# the result has passed the basic non-empty check.
TMP_OUT=""
cleanup_tmp() {
    if [[ -n "$TMP_OUT" ]]; then
        rm -f -- "$TMP_OUT"
    fi
}
trap cleanup_tmp EXIT

if [[ "$encryption" == "disabled" && "${ALLOW_UNENCRYPTED:-0}" != "1" ]]; then
    echo "$LOG_PREFIX WARNING: no AGE_RECIPIENT(_FILE) set. Backup will be plaintext on disk." >&2
fi

# --- Postgres dump ---
if [[ "$encryption" != "disabled" ]]; then
    OUT="$BACKUP_DIR/uh-$STAMP.sql.gz.age"
    echo "$LOG_PREFIX backing up $CONTAINER (encrypted) -> $OUT"
    TMP_OUT="$(mktemp "$BACKUP_DIR/.uh-$STAMP.sql.gz.age.XXXXXX")"
    docker exec "$CONTAINER" pg_dumpall -U "${POSTGRES_USER:-easylearning}" \
        | gzip \
        | run_age \
        > "$TMP_OUT"
else
    OUT="$BACKUP_DIR/uh-$STAMP.sql.gz"
    echo "$LOG_PREFIX backing up $CONTAINER -> $OUT"
    TMP_OUT="$(mktemp "$BACKUP_DIR/.uh-$STAMP.sql.gz.XXXXXX")"
    docker exec "$CONTAINER" pg_dumpall -U "${POSTGRES_USER:-easylearning}" | gzip > "$TMP_OUT"
fi

if [[ ! -s "$TMP_OUT" ]]; then
    echo "$LOG_PREFIX ERROR: backup output is empty" >&2
    exit 1
fi
chmod 600 "$TMP_OUT"
mv -f -- "$TMP_OUT" "$OUT"
TMP_OUT=""
SIZE=$(du -h "$OUT" | cut -f1)
echo "$LOG_PREFIX backup ok ($SIZE, encryption=$encryption)"

# --- .env snapshot (always encrypted if recipient is set) ---
ENV_PATH="${ENV_PATH:-/opt/university-helper/.env}"
if [[ -f "$ENV_PATH" ]]; then
    if [[ "$encryption" != "disabled" ]]; then
        ENV_OUT="$BACKUP_DIR/.env.$STAMP.age"
        TMP_OUT="$(mktemp "$BACKUP_DIR/.env.$STAMP.age.XXXXXX")"
        run_age < "$ENV_PATH" > "$TMP_OUT"
        if [[ ! -s "$TMP_OUT" ]]; then
            echo "$LOG_PREFIX ERROR: env snapshot output is empty" >&2
            exit 1
        fi
        chmod 600 "$TMP_OUT"
        mv -f -- "$TMP_OUT" "$ENV_OUT"
        TMP_OUT=""
        echo "$LOG_PREFIX env snapshotted (encrypted)"
    elif [[ "${ALLOW_UNENCRYPTED:-0}" == "1" ]]; then
        ENV_OUT="$BACKUP_DIR/.env.$STAMP"
        TMP_OUT="$(mktemp "$BACKUP_DIR/.env.$STAMP.XXXXXX")"
        cp "$ENV_PATH" "$TMP_OUT"
        chmod 600 "$TMP_OUT"
        mv -f -- "$TMP_OUT" "$ENV_OUT"
        TMP_OUT=""
        echo "$LOG_PREFIX env snapshotted (plaintext — ALLOW_UNENCRYPTED=1)"
    else
        echo "$LOG_PREFIX SKIPPING env snapshot: no AGE_RECIPIENT; refusing to write plaintext secrets"
    fi
fi

# --- Retention ---
find "$BACKUP_DIR" -name "uh-*.sql.gz*" -mtime +"$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name ".env.*" -mtime +"$RETAIN_DAYS" -delete
echo "$LOG_PREFIX retention pruned (>$RETAIN_DAYS days)"
