#!/usr/bin/env bash
# Production hotfix / deploy publisher for university-helper.
#
# Defaults target the CURRENT production box — the Aliyun ECS serving
# shuake.cornna.xyz (root@8.134.33.19, /opt/university-helper). The previous
# version of this script defaulted to a long-dead box (/opt/easy_learning,
# docker-compose.yml, easy-learning-app:8002) and could not deploy here.
#
# Box specifics baked into the defaults (see deploy memory):
#   - Compose runs via the STANDALONE `docker-compose` binary; the v2 plugin
#     (`docker compose`) SEGFAULTS on this host.
#   - Two compose files: docker-compose.server.yml + docker-compose.newhost.yml
#     (the overlay adds the `web` nginx container that serves the SPA).
#   - The SPA is served by the `web` container from a read-only bind-mount of
#     /opt/university-helper/frontend/dist, so built frontend artifacts take
#     effect as soon as they're uploaded (an `nginx -s reload` is issued to be safe).
#   - Backend hotfixes are uploaded into the remote repository checkout and
#     applied by rebuilding/replacing the app service; the app rootfs is
#     read-only, so this script never writes into the running container.
#   - The app is published on 127.0.0.1:8000, so /health is reachable locally.
#
# Transport: SSH key first; falls back to sshpass + password.
#   SERVER_IP / EASY_LEARNING_SERVER_IP        (default: 8.134.33.19)
#   SERVER_USER / EASY_LEARNING_SERVER_USER    (default: root)
#   SSH_KEY                                     path to private key (optional)
#   EASY_LEARNING_SERVER_PASSWORD               password (sshpass fallback)
#   SSH_KNOWN_HOSTS_FILE / EASY_LEARNING_SSH_KNOWN_HOSTS_FILE
#                                               trusted OpenSSH known_hosts file
#
# Usage:
#   scripts/hotfix_publish.sh backend/app/foo.py [more files...]
#   scripts/hotfix_publish.sh --frontend          # rsync the whole built dist
#   scripts/hotfix_publish.sh --dry-run <file>...  # validate and show, no network
set -euo pipefail

SERVER_IP="${SERVER_IP:-${EASY_LEARNING_SERVER_IP:-8.134.33.19}}"
SERVER_USER="${SERVER_USER:-${EASY_LEARNING_SERVER_USER:-root}}"
SERVER_PASSWORD="${EASY_LEARNING_SERVER_PASSWORD:-}"
REMOTE_DIR="${EASY_LEARNING_REMOTE_DIR:-/opt/university-helper}"
SSH_KEY="${SSH_KEY:-}"
SSH_KNOWN_HOSTS_FILE="${SSH_KNOWN_HOSTS_FILE:-${EASY_LEARNING_SSH_KNOWN_HOSTS_FILE:-}}"
DRY_RUN=0

# Standalone binary — the docker compose v2 plugin segfaults on this box.
COMPOSE_BIN="${EASY_LEARNING_COMPOSE_BIN:-docker-compose}"
# Space-separated list, expanded into repeated -f flags.
COMPOSE_FILES="${EASY_LEARNING_COMPOSE_FILES:-docker-compose.server.yml docker-compose.newhost.yml}"
COMPOSE_PROJECT="${EASY_LEARNING_COMPOSE_PROJECT:-university-helper}"

APP_CONTAINER="${EASY_LEARNING_APP_CONTAINER:-shuake-easy-learning-app}"
WEB_CONTAINER="${EASY_LEARNING_WEB_CONTAINER:-shuake-easy-learning-web}"
APP_BACKEND_DIR="${EASY_LEARNING_APP_BACKEND_DIR:-/srv/backend}"
HEALTH_URL="${EASY_LEARNING_HEALTH_URL:-http://127.0.0.1:8000/health}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

# Quote one value for use as one argument in a POSIX shell command sent over
# SSH.  ssh concatenates its command arguments and the remote shell parses the
# resulting string, so merely passing a string as an SSH argument is not
# sufficient for paths containing shell-significant characters.
shell_quote() {
  local value=$1 quoted='' char
  while [[ -n "$value" ]]; do
    char=${value%"${value#?}"}
    if [[ "$char" == "'" ]]; then
      quoted="${quoted}'\\''"
    else
      quoted="${quoted}${char}"
    fi
    value=${value#?}
  done
  printf "'%s'" "$quoted"
}

# rsync's -e value is parsed into a command and arguments a second time.  Build
# it exclusively from quoted argv values; passwords are supplied through
# SSHPASS rather than interpolated into that command string.
join_shell_words() {
  local value result=''
  for value in "$@"; do
    result="${result:+$result }$(shell_quote "$value")"
  done
  printf '%s' "$result"
}

invalid_config() {
  echo "Invalid $1: $2" >&2
  exit 1
}

validate_absolute_path() {
  local name=$1 value=$2
  [[ "$value" =~ ^/[A-Za-z0-9._/-]+$ ]] || invalid_config "$name" "must be an absolute path using only letters, digits, '.', '_', '-', and '/'"
  [[ ! "$value" =~ (^|/)\.\.?(/|$) ]] || invalid_config "$name" "must not contain '.' or '..' path components"
  [[ "$value" != */ && "$value" != "/" ]] || invalid_config "$name" "must not be the filesystem root or end with '/'"
}

validate_relative_path() {
  local name=$1 value=$2
  [[ "$value" =~ ^[A-Za-z0-9._/-]+$ && "$value" != /* && "$value" != */ ]] || invalid_config "$name" "must be a safe repository-relative path"
  [[ ! "$value" =~ (^|/)\.\.?(/|$) ]] || invalid_config "$name" "must not contain '.' or '..' path components"
}

validate_known_hosts() {
  local file=$1 host=$2 known_line first_field entry marker host_field key_type key_data
  local entry_count=0 matching_entries trusted_match=0

  [[ -n "$file" ]] || invalid_config "SSH_KNOWN_HOSTS_FILE" "must point to a preconfigured known_hosts file"
  validate_absolute_path "SSH_KNOWN_HOSTS_FILE" "$file"
  [[ -f "$file" ]] || invalid_config "SSH_KNOWN_HOSTS_FILE" "file not found"
  [[ -s "$file" ]] || invalid_config "SSH_KNOWN_HOSTS_FILE" "must not be empty"
  require_cmd ssh-keygen

  # Parse every non-comment entry locally before constructing any transport.
  # ssh-keygen -F only performs host lookup and intentionally accepts malformed
  # key blobs, so validate each key separately as a public key as well.
  while IFS= read -r known_line || [[ -n "$known_line" ]]; do
    [[ "$known_line" =~ ^[[:space:]]*$ ]] && continue
    IFS=$' \t\r' read -r first_field _ <<< "$known_line"
    [[ "$first_field" == \#* ]] && continue

    entry="$known_line"
    if [[ "$entry" == @* ]]; then
      IFS=$' \t\r' read -r marker entry <<< "$entry"
      case "$marker" in
        @cert-authority|@revoked)
          ;;
        *)
          invalid_config "SSH_KNOWN_HOSTS_FILE" "contains an unsupported marker"
          ;;
      esac
    fi

    IFS=$' \t\r' read -r host_field key_type key_data <<< "$entry"
    [[ -n "$host_field" && -n "$key_type" && -n "$key_data" ]] || invalid_config "SSH_KNOWN_HOSTS_FILE" "contains an unparseable entry"
    if ! printf '%s %s\n' "$key_type" "$key_data" | ssh-keygen -lf /dev/stdin >/dev/null 2>&1; then
      invalid_config "SSH_KNOWN_HOSTS_FILE" "contains an invalid host key"
    fi
    entry_count=$((entry_count + 1))
  done < "$file"
  (( entry_count > 0 )) || invalid_config "SSH_KNOWN_HOSTS_FILE" "contains no host keys"

  # Matching is checked separately so a syntactically valid file for another
  # host cannot accidentally authorize this deployment target.  Hashed host
  # entries are handled by ssh-keygen itself.
  matching_entries="$(ssh-keygen -F "$host" -f "$file" 2>/dev/null || true)"
  # ssh-keygen treats an explicit [host]:port entry as distinct from the
  # default-port host query.  The publisher has no separate port setting, so
  # SSH will connect on port 22 and this form is also a valid trust anchor.
  if [[ -z "$matching_entries" ]]; then
    matching_entries="$(ssh-keygen -F "[$host]:22" -f "$file" 2>/dev/null || true)"
  fi
  [[ -n "$matching_entries" ]] || invalid_config "SSH_KNOWN_HOSTS_FILE" "has no entry matching SERVER_IP"
  while IFS= read -r known_line || [[ -n "$known_line" ]]; do
    IFS=$' \t\r' read -r first_field _ <<< "$known_line"
    [[ -z "$first_field" || "$first_field" == \#* ]] && continue
    if [[ "$first_field" != "@revoked" ]]; then
      trusted_match=1
    fi
  done <<< "$matching_entries"
  (( trusted_match == 1 )) || invalid_config "SSH_KNOWN_HOSTS_FILE" "matching entry is revoked"
}

# Validate every environment-controlled command component before any ssh, scp,
# or rsync execution.  These allowlists match the identifiers and paths accepted
# by the tools below rather than attempting to blacklist shell metacharacters.
[[ -n "$SERVER_IP" ]] || { echo "Missing SERVER_IP (or EASY_LEARNING_SERVER_IP)" >&2; exit 1; }
arguments=()
for argument in "$@"; do
  if [[ "$argument" == "--dry-run" ]]; then
    DRY_RUN=1
  else
    arguments+=("$argument")
  fi
done
set -- "${arguments[@]}"
if [[ "$#" -eq 0 ]]; then
  echo "Usage: scripts/hotfix_publish.sh [--dry-run] <file> [file...]   |   --frontend" >&2
  exit 1
fi

if [[ "$SERVER_IP" == *:* ]]; then
  [[ "$SERVER_IP" =~ ^[0-9A-Fa-f:]+$ ]] || invalid_config "SERVER_IP" "must be a hostname or IP address"
  FILE_TRANSFER_HOST="[$SERVER_IP]"
else
  [[ "$SERVER_IP" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || invalid_config "SERVER_IP" "must be a hostname or IP address"
  FILE_TRANSFER_HOST="$SERVER_IP"
fi
[[ "$SERVER_USER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || invalid_config "SERVER_USER" "must be a login name"
validate_absolute_path "EASY_LEARNING_REMOTE_DIR" "$REMOTE_DIR"
validate_absolute_path "EASY_LEARNING_APP_BACKEND_DIR" "$APP_BACKEND_DIR"

if [[ "$COMPOSE_BIN" == */* ]]; then
  validate_absolute_path "EASY_LEARNING_COMPOSE_BIN" "$COMPOSE_BIN"
else
  [[ "$COMPOSE_BIN" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || invalid_config "EASY_LEARNING_COMPOSE_BIN" "must be a command name or absolute path"
fi
[[ "$COMPOSE_PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || invalid_config "EASY_LEARNING_COMPOSE_PROJECT" "must be a Compose project name"
[[ "$APP_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || invalid_config "EASY_LEARNING_APP_CONTAINER" "must be a container name"
[[ "$WEB_CONTAINER" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || invalid_config "EASY_LEARNING_WEB_CONTAINER" "must be a container name"
[[ "$HEALTH_URL" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~%/?=&+,:@-]*)?$ ]] || invalid_config "EASY_LEARNING_HEALTH_URL" "must be an absolute HTTP(S) URL without shell metacharacters"

[[ -n "$COMPOSE_FILES" && "$COMPOSE_FILES" != *[$'\001'-$'\037'$'\177']* ]] || invalid_config "EASY_LEARNING_COMPOSE_FILES" "must be a non-empty, space-separated path list"
read -r -a COMPOSE_FILE_LIST <<< "$COMPOSE_FILES"
[[ "${#COMPOSE_FILE_LIST[@]}" -gt 0 ]] || invalid_config "EASY_LEARNING_COMPOSE_FILES" "must contain at least one path"
for compose_file in "${COMPOSE_FILE_LIST[@]}"; do
  validate_relative_path "EASY_LEARNING_COMPOSE_FILES" "$compose_file"
done

if [[ -n "$SSH_KEY" ]]; then
  validate_absolute_path "SSH_KEY" "$SSH_KEY"
  [[ -f "$SSH_KEY" ]] || invalid_config "SSH_KEY" "file not found"
fi

# Build SSH/SCP/RSYNC transports.
if [[ "$DRY_RUN" == "0" ]]; then
  # This must happen before any SSH/SCP/rsync command is even constructed.
  # The file is an explicit trust anchor; never replace it with an unverified
  # first-connection scan or another implicit trust mechanism.
  validate_known_hosts "$SSH_KNOWN_HOSTS_FILE" "$SERVER_IP"
  require_cmd ssh
  require_cmd scp

  if [[ -n "$SERVER_PASSWORD" && -z "$SSH_KEY" ]]; then
    echo "WARNING: using sshpass password auth — switch to SSH keys (set SSH_KEY)." >&2
    require_cmd sshpass
    export SSHPASS="$SERVER_PASSWORD"
    SSH_PW_OPTS=(-o StrictHostKeyChecking=yes "-o" "UserKnownHostsFile=$SSH_KNOWN_HOSTS_FILE" -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=10)
    SSH_BASE=(sshpass -e ssh "${SSH_PW_OPTS[@]}" "${SERVER_USER}@${SERVER_IP}")
    SCP_BASE=(sshpass -e scp "${SSH_PW_OPTS[@]}")
    RSYNC_SSH=(sshpass -e ssh "${SSH_PW_OPTS[@]}")
  else
    SSH_OPTS=(-o StrictHostKeyChecking=yes "-o" "UserKnownHostsFile=$SSH_KNOWN_HOSTS_FILE" -o ConnectTimeout=10)
    [[ -n "$SSH_KEY" ]] && SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
    SSH_BASE=(ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_IP}")
    SCP_BASE=(scp "${SSH_OPTS[@]}")
    RSYNC_SSH=(ssh "${SSH_OPTS[@]}")
  fi
  RSYNC_RSH="$(join_shell_words "${RSYNC_SSH[@]}")"
else
  echo "Dry run: no network commands will be executed."
fi

remote_sh() { "${SSH_BASE[@]}" "$@"; }

# Expand COMPOSE_FILES into individually quoted "-f path" arguments.
compose_cmd="$(shell_quote "$COMPOSE_BIN") -p $(shell_quote "$COMPOSE_PROJECT")"
for compose_file in "${COMPOSE_FILE_LIST[@]}"; do
  compose_cmd="$compose_cmd -f $(shell_quote "$compose_file")"
done

# ── --frontend: rsync the whole built dist (handles deletes of stale hashes) ──
if [[ "$1" == "--frontend" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "Dry run: would sync frontend/dist/ to $REMOTE_DIR/frontend/dist/."
    exit 0
  fi
  require_cmd rsync
  [[ -f "$ROOT_DIR/frontend/dist/index.html" ]] || { echo "frontend/dist not built — run 'npm run build' first." >&2; exit 1; }
  echo "Backing up remote dist + syncing new build"
  remote_frontend_dir_quoted="$(shell_quote "$REMOTE_DIR/frontend")"
  remote_dist_target="${SERVER_USER}@${FILE_TRANSFER_HOST}:${REMOTE_DIR}/frontend/dist/"
  web_container_quoted="$(shell_quote "$WEB_CONTAINER")"
  remote_sh "cd $remote_frontend_dir_quoted && cp -r dist \"dist.bak.\$(date +%Y%m%d-%H%M%S)\" 2>/dev/null || true"
  rsync -az --delete -e "$RSYNC_RSH" "$ROOT_DIR/frontend/dist/" "$remote_dist_target"
  remote_sh "docker exec $web_container_quoted nginx -s reload >/dev/null 2>&1 || true"
  echo "Frontend deployed."
  exit 0
fi

# ── per-file hotfix mode ──────────────────────────────────────────────────────
needs_app_rebuild=false
needs_web_reload=false

# Resolve and validate every input before starting any remote operation.  Both
# the source path and the repository-relative path are canonicalized here; all
# upload, classification, and remote-target code below must use these validated
# values so aliases cannot change the meaning between a check and a use.
require_cmd realpath
repo_root_canonical="$(realpath "$ROOT_DIR")" || {
  echo "Unable to resolve repository root: $ROOT_DIR" >&2
  exit 1
}
validated_rel_paths=()
validated_abs_paths=()
shell_meta_chars=(
  $'\x27' $'\x22' $'\x60' $'\x24' $'\x5c'
  $'\x3b' $'\x26' $'\x7c' $'\x3c' $'\x3e'
  $'\x28' $'\x29' $'\x5b' $'\x5d' $'\x7b' $'\x7d'
  $'\x21' $'\x2a' $'\x3f'
)

for rel_path in "$@"; do
  case "$rel_path" in
    ""|/*)
      echo "Invalid repository-relative path: $rel_path" >&2
      exit 1
      ;;
    *[$'\001'-$'\037'$'\177']*)
      echo "Path contains control characters: $rel_path" >&2
      exit 1
      ;;
  esac

  for meta_char in "${shell_meta_chars[@]}"; do
    if [[ "$rel_path" == *"$meta_char"* ]]; then
      echo "Path contains shell-significant characters: $rel_path" >&2
      exit 1
    fi
  done

  # Keep the accepted CLI contract simple and unambiguous: a leading './' is
  # harmless and is canonicalized below, but no '..' component is accepted.
  # This prevents an in-repository traversal alias from bypassing the path
  # policy or changing the eventual remote destination.
  if [[ "$rel_path" =~ (^|/)\.\.(/|$) ]]; then
    echo "Path contains '..' components: $rel_path" >&2
    exit 1
  fi

  abs_path="$ROOT_DIR/$rel_path"
  if ! canonical_path="$(realpath "$abs_path" 2>/dev/null)"; then
    echo "File not found: $rel_path" >&2
    exit 1
  fi
  if [[ "$canonical_path" == *[$'\001'-$'\037'$'\177']* ]]; then
    echo "Resolved path contains control characters: $rel_path" >&2
    exit 1
  fi
  case "$canonical_path" in
    "$repo_root_canonical"/*)
      canonical_rel_path="${canonical_path#"$repo_root_canonical"/}"
      ;;
    *)
      echo "Path escapes repository root: $rel_path" >&2
      exit 1
      ;;
  esac
  [[ -f "$canonical_path" ]] || { echo "Not a regular file: $rel_path" >&2; exit 1; }

  case "$canonical_rel_path" in
    frontend/*)
      echo "Frontend source paths are not accepted in per-file mode; run 'cd frontend && npm ci && npm run build', then from the repository root './scripts/hotfix_publish.sh --frontend'." >&2
      exit 1
      ;;
    .env|.env.*)
      echo "Sensitive repository paths are not accepted in per-file mode." >&2
      exit 1
      ;;
  esac

  validated_rel_paths+=("$canonical_rel_path")
  validated_abs_paths+=("$canonical_path")
done

# Classify only after every source path has passed canonicalization.  This is
# intentionally done before the first remote operation so backend updates can
# fail closed when the selected remote Compose topology cannot build the app.
for rel_path in "${validated_rel_paths[@]}"; do
  case "$rel_path" in
    backend/*|Dockerfile.server|docker-compose*.yml)
      needs_app_rebuild=true
      ;;
    frontend/*|nginx/nginx.conf|nginx/proxy_params.conf|nginx/snippets/*)
      needs_web_reload=true
      ;;
  esac
done

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'Dry run: validated %d repository path(s):\n' "${#validated_rel_paths[@]}"
  printf '  %s\n' "${validated_rel_paths[@]}"
  exit 0
fi

if [[ "$needs_app_rebuild" != true ]]; then
  # Keep the existing non-backend per-file path (for example nginx reference
  # configuration) independent from the app image transaction below.
  for index in "${!validated_rel_paths[@]}"; do
    rel_path="${validated_rel_paths[$index]}"
    abs_path="${validated_abs_paths[$index]}"
    remote_path="$REMOTE_DIR/$rel_path"
    remote_dir="$(dirname "$remote_path")"
    remote_path_quoted="$(shell_quote "$remote_path")"
    remote_dir_quoted="$(shell_quote "$remote_dir")"
    remote_sh "mkdir -p $remote_dir_quoted"
    "${SCP_BASE[@]}" "$abs_path" "${SERVER_USER}@${FILE_TRANSFER_HOST}:${remote_path}"
  done

  if [[ "$needs_web_reload" == true ]]; then
    echo "Reloading web nginx ($WEB_CONTAINER)"
    web_container_quoted="$(shell_quote "$WEB_CONTAINER")"
    remote_sh "docker exec $web_container_quoted nginx -s reload >/dev/null 2>&1 || true"
  fi

  echo "Waiting for app health ($HEALTH_URL)"
  health_url_quoted="$(shell_quote "$HEALTH_URL")"
  remote_sh "for i in \$(seq 1 30); do if curl -fsS --max-time 5 $health_url_quoted >/dev/null 2>&1; then exit 0; fi; sleep 2; done; exit 1"
  echo "Hotfix publish complete."
  exit 0
fi

# Compose's JSON output is the source of truth for the build context.  The
# validator resolves both context and Dockerfile through realpath on the
# remote host and rejects symlink/path escapes before any source is uploaded.
compose_build_validator_py='
import json
import os
import sys

def fail(message):
    raise SystemExit(message)

try:
    document = json.load(sys.stdin)
except Exception as exc:
    fail("invalid Compose JSON: " + str(exc))

root = os.path.realpath(sys.argv[1])
services = document.get("services")
app = services.get("app") if isinstance(services, dict) else None
build = app.get("build") if isinstance(app, dict) else None
if not isinstance(build, dict):
    fail("services.app.build is missing")
context = build.get("context")
if not isinstance(context, str) or not context:
    fail("services.app.build.context is missing")
context_path = os.path.realpath(context if os.path.isabs(context) else os.path.join(root, context))
if not os.path.isdir(context_path):
    fail("services.app.build.context does not exist")
try:
    if os.path.commonpath((root, context_path)) != root:
        fail("services.app.build.context escapes the repository checkout")
except ValueError:
    fail("services.app.build.context is on another filesystem root")
dockerfile = build.get("dockerfile", "Dockerfile")
if not isinstance(dockerfile, str) or not dockerfile:
    fail("services.app.build.dockerfile is invalid")
dockerfile_path = os.path.realpath(dockerfile if os.path.isabs(dockerfile) else os.path.join(context_path, dockerfile))
try:
    if os.path.commonpath((context_path, dockerfile_path)) != context_path:
        fail("services.app.build.dockerfile escapes the build context")
except ValueError:
    fail("services.app.build.dockerfile is on another filesystem root")
if not os.path.isfile(dockerfile_path):
    fail("services.app.build.dockerfile does not exist")
print("build-context-ok")
'
compose_build_validator_quoted="$(shell_quote "$compose_build_validator_py")"
compose_image_ref_py='
import json
import sys

# hotfix-image-ref
document = json.load(sys.stdin)
services = document.get("services")
app = services.get("app") if isinstance(services, dict) else None
image = app.get("image") if isinstance(app, dict) else None
if not isinstance(image, str) or not image:
    raise SystemExit("services.app.image is missing")
print(image)
'
compose_image_ref_quoted="$(shell_quote "$compose_image_ref_py")"
remote_dir_quoted="$(shell_quote "$REMOTE_DIR")"
app_container_quoted="$(shell_quote "$APP_CONTAINER")"

validate_remote_build_context() {
  local phase=$1 context_command
  context_command="cd $remote_dir_quoted && test -d . && config_output=\$($compose_cmd config --format json) && printf '%s\\n' \"\$config_output\" | python3 -c $compose_build_validator_quoted $remote_dir_quoted"
  if ! remote_sh "$context_command"; then
    echo "Remote Compose build-context validation failed ($phase); refusing backend hotfix." >&2
    return 1
  fi
}

echo "Validating remote Compose build context"
if ! validate_remote_build_context "before upload"; then
  exit 1
fi

# Capture the state needed for a deterministic rollback before touching the
# checkout.  IDs are validated locally before being interpolated into any
# later remote command.
old_app_record="$(remote_sh "docker inspect --format '{{.Id}}|{{.Image}}' $app_container_quoted")"
IFS='|' read -r old_app_container_id old_app_image_id <<< "$old_app_record"
if [[ ! "$old_app_container_id" =~ ^[[:xdigit:]]{12,64}$ || ! "$old_app_image_id" =~ ^sha256:[[:xdigit:]]{12,64}$ ]]; then
  echo "Unable to record the current app container/image IDs; refusing backend hotfix." >&2
  exit 1
fi
compose_image_query="cd $remote_dir_quoted && config_output=\$($compose_cmd config --format json) && printf '%s\\n' \"\$config_output\" | python3 -c $compose_image_ref_quoted"
old_app_image_ref="$(remote_sh "$compose_image_query")"
if [[ ! "$old_app_image_ref" =~ ^[A-Za-z0-9._/@:+-]+$ ]]; then
  echo "Unable to record a safe Compose app image reference; refusing backend hotfix." >&2
  exit 1
fi
old_app_image_id_quoted="$(shell_quote "$old_app_image_id")"
old_app_image_ref_quoted="$(shell_quote "$old_app_image_ref")"

published_remote_paths=()
backup_remote_paths=()
source_states=()
stage_remote_paths=()
transaction_active=1
operation="initializing backend hotfix transaction"

cleanup_remote_transaction() {
  local cleanup_command=":" index path_quoted
  for index in "${!stage_remote_paths[@]}"; do
    if [[ -n "${stage_remote_paths[$index]}" ]]; then
      path_quoted="$(shell_quote "${stage_remote_paths[$index]}")"
      cleanup_command+=" && rm -f $path_quoted"
    fi
  done
  for index in "${!backup_remote_paths[@]}"; do
    if [[ -n "${backup_remote_paths[$index]}" ]]; then
      path_quoted="$(shell_quote "${backup_remote_paths[$index]}")"
      cleanup_command+=" && rm -f $path_quoted"
    fi
  done
  remote_sh "$cleanup_command"
}

restore_remote_sources() {
  local restore_command=":" index target_quoted path_quoted
  for index in "${!published_remote_paths[@]}"; do
    target_quoted="$(shell_quote "${published_remote_paths[$index]}")"
    if [[ -n "${stage_remote_paths[$index]}" ]]; then
      path_quoted="$(shell_quote "${stage_remote_paths[$index]}")"
      restore_command+=" && rm -f $path_quoted"
    fi
    case "${source_states[$index]}" in
      existing)
        path_quoted="$(shell_quote "${backup_remote_paths[$index]}")"
        restore_command+=" && cp -p -- $path_quoted $target_quoted"
        ;;
      missing)
        restore_command+=" && rm -f $target_quoted"
        ;;
      unknown)
        ;;
      *)
        return 1
        ;;
    esac
  done
  remote_sh "$restore_command"
}

rollback_transaction() {
  local rollback_status=0 rollback_health_command rollback_record
  local rollback_container_id rollback_container_id_quoted rollback_image_id
  trap - ERR
  transaction_active=0
  set +e
  echo "Attempting backend hotfix rollback" >&2

  if ! restore_remote_sources; then
    rollback_status=1
  fi
  if (( rollback_status == 0 )); then
    if ! remote_sh "docker tag $old_app_image_id_quoted $old_app_image_ref_quoted"; then
      rollback_status=1
    fi
  fi
  if (( rollback_status == 0 )); then
    if ! remote_sh "cd $remote_dir_quoted && $compose_cmd up -d --no-build --force-recreate --no-deps app"; then
      rollback_status=1
    fi
  fi
  if (( rollback_status == 0 )); then
    rollback_record="$(remote_sh "docker inspect --format '{{.Image}}|{{.Id}}' $app_container_quoted")"
    IFS='|' read -r rollback_image_id rollback_container_id <<< "$rollback_record"
    if [[ ! "$rollback_container_id" =~ ^[[:xdigit:]]{12,64}$ || "$rollback_image_id" != "$old_app_image_id" ]]; then
      rollback_status=1
    fi
  fi
  if (( rollback_status == 0 )); then
    rollback_container_id_quoted="$(shell_quote "$rollback_container_id")"
    rollback_health_command="for i in \$(seq 1 30); do status=\$(docker inspect --format '{{.State.Health.Status}}' $rollback_container_id_quoted 2>/dev/null || true); if [ \"\$status\" = healthy ]; then exit 0; fi; if [ \"\$status\" = unhealthy ]; then exit 1; fi; sleep 2; done; exit 1"
    if ! remote_sh "$rollback_health_command"; then
      rollback_status=1
    fi
  fi
  if (( rollback_status == 0 )); then
    if ! cleanup_remote_transaction; then
      rollback_status=1
    fi
  fi
  set -e
  if (( rollback_status != 0 )); then
    echo "FATAL: backend hotfix rollback failed; source backups and deployment state require manual recovery." >&2
    return 1
  fi
  echo "Backend hotfix rollback completed and app health is healthy; app image $old_app_image_id is restored." >&2
  return 0
}

on_error() {
  local status=${1:-1}
  trap - ERR
  if [[ "$transaction_active" == "1" ]]; then
    echo "Hotfix failed during $operation; no success declared." >&2
    if ! rollback_transaction; then
      echo "FATAL: rollback did not complete; no success declared." >&2
    fi
  fi
  exit "$status"
}

abort_transaction() {
  echo "Hotfix failed: $*" >&2
  on_error 1
}

run_remote_checked() {
  local status
  if remote_sh "$@"; then
    return 0
  else
    status=$?
    on_error "$status"
  fi
}

run_scp_checked() {
  local status
  if "${SCP_BASE[@]}" "$@"; then
    return 0
  else
    status=$?
    on_error "$status"
  fi
}

trap 'on_error "$?"' ERR

for index in "${!validated_rel_paths[@]}"; do
  rel_path="${validated_rel_paths[$index]}"
  abs_path="${validated_abs_paths[$index]}"
  remote_path="$REMOTE_DIR/$rel_path"
  remote_dir="$(dirname "$remote_path")"
  remote_path_quoted="$(shell_quote "$remote_path")"
  remote_dir_for_file_quoted="$(shell_quote "$remote_dir")"
  backup_template_quoted="$(shell_quote "$remote_path.hotfix-backup.XXXXXX")"
  stage_template_quoted="$(shell_quote "$remote_path.hotfix-stage.XXXXXX")"
  published_remote_paths[index]="$remote_path"
  backup_remote_paths[index]=""
  source_states[index]="unknown"
  stage_remote_paths[index]=""

  operation="creating backup for $rel_path"
  run_remote_checked "mkdir -p $remote_dir_for_file_quoted"
  if backup_record="$(remote_sh "set -e; if [ -e $remote_path_quoted ]; then backup_path=\$(mktemp $backup_template_quoted); cp -p -- $remote_path_quoted \"\$backup_path\"; printf 'existing|%s\\n' \"\$backup_path\"; else printf 'missing|\\n'; fi")"; then
    :
  else
    status=$?
    on_error "$status"
  fi
  case "$backup_record" in
    existing\|*)
      backup_path=${backup_record#existing|}
      if [[ "$backup_path" != "$remote_path.hotfix-backup."* ]]; then
        abort_transaction "remote backup path is not a unique same-directory mktemp path for $rel_path"
      fi
      backup_remote_paths[index]="$backup_path"
      source_states[index]="existing"
      ;;
    missing\|)
      source_states[index]="missing"
      ;;
    *)
      abort_transaction "unable to record the pre-hotfix source state for $rel_path"
      ;;
  esac

  operation="creating staging file for $rel_path"
  if stage_path="$(remote_sh "set -e; stage_path=\$(mktemp $stage_template_quoted); printf '%s\\n' \"\$stage_path\"")"; then
    :
  else
    status=$?
    on_error "$status"
  fi
  if [[ "$stage_path" != "$remote_path.hotfix-stage."* ]]; then
    abort_transaction "remote staging path is not a unique same-directory mktemp path for $rel_path"
  fi
  stage_remote_paths[index]="$stage_path"
  stage_path_quoted="$(shell_quote "$stage_path")"

  operation="uploading staged $rel_path"
  run_scp_checked "$abs_path" "${SERVER_USER}@${FILE_TRANSFER_HOST}:${stage_path}"
  operation="atomically publishing $rel_path"
  run_remote_checked "mv -f $stage_path_quoted $remote_path_quoted"
  stage_remote_paths[index]=""
done

operation="revalidating remote Compose build context after upload"
validate_remote_build_context "after upload" || on_error "$?"

operation="rebuilding and replacing app container"
echo "Rebuilding app image from remote repository checkout"
run_remote_checked "cd $remote_dir_quoted && $compose_cmd up -d --build --no-deps --force-recreate app"

operation="checking app container identity"
if new_app_container_id="$(remote_sh "docker inspect --format '{{.Id}}' $app_container_quoted")"; then
  :
else
  status=$?
  on_error "$status"
fi
if [[ ! "$new_app_container_id" =~ ^[[:xdigit:]]{12,64}$ ]]; then
  abort_transaction "unable to record the replacement app container ID"
fi
if [[ "$new_app_container_id" == "$old_app_container_id" ]]; then
  abort_transaction "Compose did not replace the app container (identity is unchanged)"
fi
new_app_container_id_quoted="$(shell_quote "$new_app_container_id")"

operation="checking replacement app image identity"
if new_app_image_id="$(remote_sh "docker inspect --format '{{.Image}}' $new_app_container_id_quoted")"; then
  :
else
  status=$?
  on_error "$status"
fi
if [[ ! "$new_app_image_id" =~ ^sha256:[[:xdigit:]]{64}$ ]]; then
  abort_transaction "replacement app image ID is empty or is not a full sha256 digest"
fi
if [[ "$new_app_image_id" == "$old_app_image_id" ]]; then
  abort_transaction "Compose replaced the app container but its image identity is unchanged"
fi

operation="checking Compose app image identity"
if compose_app_image_id="$(remote_sh "cd $remote_dir_quoted && $compose_cmd images -q app")"; then
  :
else
  status=$?
  on_error "$status"
fi
if [[ "$compose_app_image_id" =~ ^[[:xdigit:]]{12,64}$ ]]; then
  compose_app_image_id_quoted="$(shell_quote "$compose_app_image_id")"
  if compose_app_image_id="$(remote_sh "docker image inspect --format '{{.Id}}' $compose_app_image_id_quoted")"; then
    :
  else
    status=$?
    on_error "$status"
  fi
fi
if [[ ! "$compose_app_image_id" =~ ^sha256:[[:xdigit:]]{64}$ ]]; then
  abort_transaction "Compose app image ID is empty or is not a full sha256 digest"
fi
if [[ "$compose_app_image_id" != "$new_app_image_id" ]]; then
  abort_transaction "replacement container image does not match the Compose app image"
fi

operation="waiting for replacement app Compose health"
app_health_poll_command="for i in \$(seq 1 30); do status=\$(docker inspect --format '{{.State.Health.Status}}' $new_app_container_id_quoted 2>/dev/null || true); if [ \"\$status\" = healthy ]; then exit 0; fi; if [ \"\$status\" = unhealthy ]; then exit 1; fi; sleep 2; done; exit 1"
run_remote_checked "$app_health_poll_command"

if [[ "$needs_web_reload" == true ]]; then
  echo "Reloading web nginx ($WEB_CONTAINER)"
  web_container_quoted="$(shell_quote "$WEB_CONTAINER")"
  remote_sh "docker exec $web_container_quoted nginx -s reload >/dev/null 2>&1 || true"
fi

operation="checking replacement app HTTP health"
echo "Waiting for app health ($HEALTH_URL)"
health_url_quoted="$(shell_quote "$HEALTH_URL")"
run_remote_checked "for i in \$(seq 1 30); do if curl -fsS --max-time 5 $health_url_quoted >/dev/null 2>&1; then exit 0; fi; sleep 2; done; exit 1"

operation="cleaning successful hotfix staging and backups"
cleanup_remote_transaction || on_error "$?"
transaction_active=0
trap - ERR
echo "Hotfix publish complete. App container $old_app_container_id -> $new_app_container_id; image $old_app_image_id -> $new_app_image_id."
