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
RETAIN_DAYS_INPUT="${RETAIN_DAYS-14}"
CONTAINER="${BACKUP_CONTAINER:-shuake-easy-learning-db}"

# Parse retention as decimal before creating directories or producing data.
# The 100-year ceiling also keeps the seconds conversion safely bounded.
MAX_RETAIN_DAYS=36500
if [[ ! "$RETAIN_DAYS_INPUT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: RETAIN_DAYS must be a non-negative decimal integer" >&2
    exit 2
fi
if [[ "$RETAIN_DAYS_INPUT" =~ ^0*([0-9]+)$ ]]; then
    RETAIN_DAYS_DECIMAL="${BASH_REMATCH[1]}"
else
    echo "ERROR: unable to parse RETAIN_DAYS" >&2
    exit 2
fi
if ((${#RETAIN_DAYS_DECIMAL} > ${#MAX_RETAIN_DAYS})); then
    echo "ERROR: RETAIN_DAYS must not exceed $MAX_RETAIN_DAYS" >&2
    exit 2
fi
RETAIN_DAYS=$((10#$RETAIN_DAYS_DECIMAL))
if ((RETAIN_DAYS > MAX_RETAIN_DAYS)); then
    echo "ERROR: RETAIN_DAYS must not exceed $MAX_RETAIN_DAYS" >&2
    exit 2
fi

# Test hooks are ignored unless explicitly enabled, and unsafe/unhandled
# signals are rejected before any backup side effect.
TEST_SIGNAL_AFTER_RESERVATION_MKDIR=""
TEST_SIGNAL_AFTER_PUBLISH_LINK=""
if [[ "${DB_BACKUP_TEST_MODE:-0}" == "1" ]]; then
    for test_signal in \
        "${DB_BACKUP_TEST_SIGNAL_AFTER_RESERVATION_MKDIR:-}" \
        "${DB_BACKUP_TEST_SIGNAL_AFTER_PUBLISH_LINK:-}"; do
        case "$test_signal" in
            "" | HUP | INT | TERM) ;;
            *)
                echo "ERROR: invalid DB backup test signal" >&2
                exit 2
                ;;
        esac
    done
    TEST_SIGNAL_AFTER_RESERVATION_MKDIR="${DB_BACKUP_TEST_SIGNAL_AFTER_RESERVATION_MKDIR:-}"
    TEST_SIGNAL_AFTER_PUBLISH_LINK="${DB_BACKUP_TEST_SIGNAL_AFTER_PUBLISH_LINK:-}"
fi

STAMP="$(date +%F-%H%M%S)"
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

# Give every invocation an exclusive, per-run workspace.  The mktemp suffix
# is part of GROUP_ID, so runs with the same clock value still get distinct,
# sortable names while their SQL and .env snapshots remain associated.
RUN_TMP_DIR=""
TMP_OUT=""
RESERVATION=""
RESERVATION_STATE=0 # 0=unowned/candidate, 1=mkdir in flight, 2=owned
cleanup_tmp() {
    local exit_code=$?

    if [[ -n "$TMP_OUT" ]]; then
        rm -f -- "$TMP_OUT" || true
    fi
    if [[ -n "$RESERVATION" && "$RESERVATION_STATE" -eq 2 ]]; then
        rmdir "$RESERVATION" 2>/dev/null || true
    fi
    if [[ -n "$RUN_TMP_DIR" ]]; then
        # Only remove our own empty workspace; never recursively remove a
        # path that could contain another invocation's temporary files.
        rmdir "$RUN_TMP_DIR" 2>/dev/null || true
    fi
    return "$exit_code"
}
trap cleanup_tmp EXIT

exit_on_signal() {
    # A trapped signal can be delivered after mkdir has returned but before
    # Bash enters its success branch.  Preserve that command status before
    # any handler command changes it, and complete the ownership transition
    # only when mkdir succeeded.
    local command_status=$?
    local signal_number="$1"

    if [[ "$RESERVATION_STATE" -eq 1 && "$command_status" -eq 0 ]]; then
        RESERVATION_STATE=2
    fi
    trap - HUP INT TERM
    exit $((128 + signal_number))
}
trap 'exit_on_signal 1' HUP
trap 'exit_on_signal 2' INT
trap 'exit_on_signal 15' TERM

RUN_TMP_DIR="$(mktemp -d "$BACKUP_DIR/.uh-$STAMP.XXXXXX")"
GROUP_ID="${RUN_TMP_DIR##*/}"
GROUP_ID="${GROUP_ID#.uh-}"

publish_no_clobber() {
    local source="$1"
    local destination="$2"
    local reservation="$destination.reserve"

    # Reserve the destination name first.  The reservation is a directory so
    # mkdir is an atomic, portable no-clobber operation on macOS and Linux;
    # every invocation uses the same reservation name, so concurrent runs do
    # not race through the existence check below.
    # Register the candidate before mkdir so EXIT/signal cleanup can see it.
    # The arithmetic condition both enters the in-flight state and returns a
    # deliberate non-zero sentinel.  A signal before mkdir therefore cannot
    # be mistaken for a successful claim; a signal after a successful mkdir
    # is promoted to owned by exit_on_signal using mkdir's saved status.
    RESERVATION="$reservation"
    if ((RESERVATION_STATE = 1, 0)); then
        echo "$LOG_PREFIX ERROR: internal reservation state error" >&2
        return 1
    elif mkdir "$reservation" 2>/dev/null; then
        # Keep the production path's ownership assignment as the first simple
        # command after mkdir.  The test-only alternatives synchronously
        # signal this shell at that exact success-to-assignment boundary.
        case "$TEST_SIGNAL_AFTER_RESERVATION_MKDIR" in
            "") RESERVATION_STATE=2 ;;
            HUP | INT | TERM)
                kill -s "$TEST_SIGNAL_AFTER_RESERVATION_MKDIR" "$$"
                ;;
            *)
                RESERVATION_STATE=2
                echo "$LOG_PREFIX ERROR: invalid reservation test signal" >&2
                return 2
                ;;
        esac
    else
        RESERVATION_STATE=0
        RESERVATION=""
        echo "$LOG_PREFIX ERROR: refusing to overwrite existing backup: $destination" >&2
        return 1
    fi

    # Check all object types.  In particular, ln source destination treats an
    # existing directory as a target directory and would otherwise create a
    # nested link while reporting success.
    if [[ -e "$destination" || -L "$destination" ]]; then
        echo "$LOG_PREFIX ERROR: refusing to overwrite existing backup: $destination" >&2
        return 1
    fi

    # A hard link creates the destination atomically and fails if it appears
    # after the check.  The source and destination are on BACKUP_DIR's
    # filesystem, so this avoids cross-filesystem rename surprises.
    if ! ln "$source" "$destination"; then
        echo "$LOG_PREFIX ERROR: refusing to overwrite existing backup: $destination" >&2
        return 1
    fi
    # Test-only hook proving cleanup never removes an already linked target.
    if [[ -n "$TEST_SIGNAL_AFTER_PUBLISH_LINK" ]]; then
        kill -s "$TEST_SIGNAL_AFTER_PUBLISH_LINK" "$$"
    fi
    rm -f -- "$source"
    TMP_OUT=""
    rmdir "$reservation"
    RESERVATION_STATE=0
    RESERVATION=""
}

if [[ "$encryption" == "disabled" && "${ALLOW_UNENCRYPTED:-0}" != "1" ]]; then
    echo "$LOG_PREFIX WARNING: no AGE_RECIPIENT(_FILE) set. Backup will be plaintext on disk." >&2
fi

# --- Postgres dump ---
if [[ "$encryption" != "disabled" ]]; then
    OUT="$BACKUP_DIR/uh-$GROUP_ID.sql.gz.age"
    echo "$LOG_PREFIX backing up $CONTAINER (encrypted) -> $OUT"
    TMP_OUT="$(mktemp "$RUN_TMP_DIR/db.XXXXXX")"
    docker exec "$CONTAINER" pg_dumpall -U "${POSTGRES_USER:-easylearning}" \
        | gzip \
        | run_age \
        > "$TMP_OUT"
else
    OUT="$BACKUP_DIR/uh-$GROUP_ID.sql.gz"
    echo "$LOG_PREFIX backing up $CONTAINER -> $OUT"
    TMP_OUT="$(mktemp "$RUN_TMP_DIR/db.XXXXXX")"
    docker exec "$CONTAINER" pg_dumpall -U "${POSTGRES_USER:-easylearning}" | gzip > "$TMP_OUT"
fi

if [[ ! -s "$TMP_OUT" ]]; then
    echo "$LOG_PREFIX ERROR: backup output is empty" >&2
    exit 1
fi
chmod 600 "$TMP_OUT"
publish_no_clobber "$TMP_OUT" "$OUT"
SIZE=$(du -h "$OUT" | cut -f1)
echo "$LOG_PREFIX backup ok ($SIZE, encryption=$encryption)"

# --- .env snapshot (always encrypted if recipient is set) ---
ENV_PATH="${ENV_PATH:-/opt/university-helper/.env}"
if [[ -f "$ENV_PATH" ]]; then
    if [[ "$encryption" != "disabled" ]]; then
        ENV_OUT="$BACKUP_DIR/.env.$GROUP_ID.age"
        TMP_OUT="$(mktemp "$RUN_TMP_DIR/env.XXXXXX")"
        run_age < "$ENV_PATH" > "$TMP_OUT"
        if [[ ! -s "$TMP_OUT" ]]; then
            echo "$LOG_PREFIX ERROR: env snapshot output is empty" >&2
            exit 1
        fi
        chmod 600 "$TMP_OUT"
        publish_no_clobber "$TMP_OUT" "$ENV_OUT"
        echo "$LOG_PREFIX env snapshotted (encrypted)"
    elif [[ "${ALLOW_UNENCRYPTED:-0}" == "1" ]]; then
        ENV_OUT="$BACKUP_DIR/.env.$GROUP_ID"
        TMP_OUT="$(mktemp "$RUN_TMP_DIR/env.XXXXXX")"
        cp "$ENV_PATH" "$TMP_OUT"
        chmod 600 "$TMP_OUT"
        publish_no_clobber "$TMP_OUT" "$ENV_OUT"
        echo "$LOG_PREFIX env snapshotted (plaintext — ALLOW_UNENCRYPTED=1)"
    else
        echo "$LOG_PREFIX SKIPPING env snapshot: no AGE_RECIPIENT; refusing to write plaintext secrets"
    fi
fi

# --- Retention ---
NOW_EPOCH="$(date +%s)"
CUTOFF_EPOCH=$((NOW_EPOCH - RETAIN_DAYS * 86400))

backup_group_from_path() {
    local name="${1##*/}"
    local group_re='^uh-([0-9]{4}-[0-9]{2}-[0-9]{2}-([0-9]{4}|[0-9]{6}\.[[:alnum:]]{6}))\.sql\.gz(\.age)?$'
    local env_re='^\.env\.([0-9]{4}-[0-9]{2}-[0-9]{2}-([0-9]{4}|[0-9]{6}\.[[:alnum:]]{6}))(\.age)?$'

    if [[ "$name" =~ $group_re ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    elif [[ "$name" =~ $env_re ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        return 1
    fi
}

backup_mtime() {
    local path="$1"
    local mtime

    if mtime="$(stat -c %Y "$path" 2>/dev/null)"; then
        printf '%s\n' "$mtime"
    elif mtime="$(stat -f %m "$path" 2>/dev/null)"; then
        printf '%s\n' "$mtime"
    else
        return 1
    fi
}

retention_consider_group() {
    local candidate="$1"
    local group
    local path
    local mtime
    local newest_mtime=0
    local -a members=()

    group="$(backup_group_from_path "$candidate")" || return 0
    # Only these four exact generated names can be considered.  This keeps
    # ordinary .env files and malformed lookalikes outside retention.
    for path in \
        "$BACKUP_DIR/uh-$group.sql.gz" \
        "$BACKUP_DIR/uh-$group.sql.gz.age" \
        "$BACKUP_DIR/.env.$group" \
        "$BACKUP_DIR/.env.$group.age"; do
        if [[ -f "$path" && ! -L "$path" ]]; then
            members+=("$path")
        fi
    done

    # A recognized orphan is eligible based on its own age.  When both
    # members exist, the newest member controls the group so a fresh member
    # prevents deletion of its older companion.
    for path in "${members[@]}"; do
        mtime="$(backup_mtime "$path")" || {
            echo "$LOG_PREFIX WARNING: unable to read backup mtime: $path" >&2
            return 0
        }
        if ((mtime > newest_mtime)); then
            newest_mtime="$mtime"
        fi
    done

    # Retain files exactly on the cutoff: they are not older than the
    # configured window.  This also keeps a just-published backup when the
    # clock and filesystem mtime share the same second (notably with
    # RETAIN_DAYS=0).
    if ((newest_mtime >= CUTOFF_EPOCH)); then
        return 0
    fi
    for path in "${members[@]}"; do
        rm -f -- "$path"
    done
}

# Scan only names with the generated timestamp shape, then apply the strict
# parser above.  The parser supports both legacy minute stamps and current
# second-plus-random group IDs.
for candidate in \
    "$BACKUP_DIR"/uh-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.sql.gz \
    "$BACKUP_DIR"/uh-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.sql.gz.age \
    "$BACKUP_DIR"/.env.[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*; do
    if [[ -f "$candidate" && ! -L "$candidate" ]]; then
        retention_consider_group "$candidate"
    fi
done
echo "$LOG_PREFIX retention pruned (>$RETAIN_DAYS days)"
