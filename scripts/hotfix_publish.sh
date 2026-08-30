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
#     /opt/university-helper/frontend/dist, so frontend files take effect as
#     soon as they're uploaded (an `nginx -s reload` is issued to be safe).
#   - Backend code lives at /srv/backend inside the app container.
#   - The app is published on 127.0.0.1:8000, so /health is reachable locally.
#
# Transport: SSH key first; falls back to sshpass + password.
#   SERVER_IP / EASY_LEARNING_SERVER_IP        (default: 8.134.33.19)
#   SERVER_USER / EASY_LEARNING_SERVER_USER    (default: root)
#   SSH_KEY                                     path to private key (optional)
#   EASY_LEARNING_SERVER_PASSWORD               password (sshpass fallback)
#
# Usage:
#   scripts/hotfix_publish.sh backend/app/foo.py [more files...]
#   scripts/hotfix_publish.sh --frontend          # rsync the whole built dist
set -euo pipefail

SERVER_IP="${SERVER_IP:-${EASY_LEARNING_SERVER_IP:-8.134.33.19}}"
SERVER_USER="${SERVER_USER:-${EASY_LEARNING_SERVER_USER:-root}}"
SERVER_PASSWORD="${EASY_LEARNING_SERVER_PASSWORD:-}"
REMOTE_DIR="${EASY_LEARNING_REMOTE_DIR:-/opt/university-helper}"
SSH_KEY="${SSH_KEY:-}"

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

if [[ -z "$SERVER_IP" ]]; then
  echo "Missing SERVER_IP (or EASY_LEARNING_SERVER_IP)" >&2
  exit 1
fi
if [[ "$#" -eq 0 ]]; then
  echo "Usage: scripts/hotfix_publish.sh <file> [file...]   |   --frontend" >&2
  exit 1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
require_cmd ssh
require_cmd scp

# Build SSH/SCP/RSYNC transports.
if [[ -n "$SERVER_PASSWORD" && -z "$SSH_KEY" ]]; then
  echo "WARNING: using sshpass password auth — switch to SSH keys (set SSH_KEY)." >&2
  require_cmd sshpass
  SSH_PW_OPTS=(-o StrictHostKeyChecking=accept-new -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=10)
  SSH_BASE=(sshpass -p "$SERVER_PASSWORD" ssh "${SSH_PW_OPTS[@]}" "${SERVER_USER}@${SERVER_IP}")
  SCP_BASE=(sshpass -p "$SERVER_PASSWORD" scp "${SSH_PW_OPTS[@]}")
  RSYNC_RSH="sshpass -p $SERVER_PASSWORD ssh ${SSH_PW_OPTS[*]}"
else
  SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
  [[ -n "$SSH_KEY" ]] && SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
  SSH_BASE=(ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_IP}")
  SCP_BASE=(scp "${SSH_OPTS[@]}")
  RSYNC_RSH="ssh ${SSH_OPTS[*]}"
fi

remote_sh() { "${SSH_BASE[@]}" "$@"; }

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

# Expand COMPOSE_FILES into "-f a -f b".
compose_f_args() { local f; for f in $COMPOSE_FILES; do printf -- "-f %s " "$f"; done; }
compose_cmd="$COMPOSE_BIN -p $COMPOSE_PROJECT $(compose_f_args)"

# ── --frontend: rsync the whole built dist (handles deletes of stale hashes) ──
if [[ "$1" == "--frontend" ]]; then
  require_cmd rsync
  [[ -f "$ROOT_DIR/frontend/dist/index.html" ]] || { echo "frontend/dist not built — run 'npm run build' first." >&2; exit 1; }
  echo "Backing up remote dist + syncing new build"
  remote_sh "cd '$REMOTE_DIR/frontend' && cp -r dist \"dist.bak.\$(date +%Y%m%d-%H%M%S)\" 2>/dev/null || true"
  rsync -az --delete -e "$RSYNC_RSH" "$ROOT_DIR/frontend/dist/" "${SERVER_USER}@${SERVER_IP}:$REMOTE_DIR/frontend/dist/"
  remote_sh "docker exec '$WEB_CONTAINER' nginx -s reload >/dev/null 2>&1 || true"
  echo "Frontend deployed."
  exit 0
fi

# ── per-file hotfix mode ──────────────────────────────────────────────────────
needs_app_rebuild=false
needs_app_hotcopy=false
needs_web_reload=false
backend_files=()

# Resolve and validate every input before starting any remote operation.  Keep
# the canonical source path so a symlink cannot be swapped after validation to
# make scp read a file outside the repository.
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
    "$repo_root_canonical"/*) ;;
    *)
      echo "Path escapes repository root: $rel_path" >&2
      exit 1
      ;;
  esac
  [[ -f "$canonical_path" ]] || { echo "Not a regular file: $rel_path" >&2; exit 1; }

  validated_rel_paths+=("$rel_path")
  validated_abs_paths+=("$canonical_path")
done

for index in "${!validated_rel_paths[@]}"; do
  rel_path="${validated_rel_paths[$index]}"
  abs_path="${validated_abs_paths[$index]}"
  remote_path="$REMOTE_DIR/$rel_path"
  remote_dir="$(dirname "$remote_path")"
  remote_path_quoted="$(shell_quote "$remote_path")"
  remote_dir_quoted="$(shell_quote "$remote_dir")"
  remote_sh "mkdir -p $remote_dir_quoted"
  "${SCP_BASE[@]}" "$abs_path" "${SERVER_USER}@${SERVER_IP}:$remote_path"

  case "$rel_path" in
    backend/*) backend_files+=("$rel_path"); needs_app_hotcopy=true ;;
  esac
  case "$rel_path" in
    Dockerfile.server|backend/requirements.txt|backend/pyproject.toml|docker-compose*.yml)
      needs_app_rebuild=true ;;
    frontend/*|nginx/nginx.conf|nginx/proxy_params.conf)
      needs_web_reload=true ;;
  esac
done

if [[ "$needs_app_rebuild" == true ]]; then
  echo "Rebuilding app image"
  remote_sh "cd '$REMOTE_DIR' && $compose_cmd up -d --build app"
elif [[ "$needs_app_hotcopy" == true ]]; then
  echo "Hot-copying backend files into $APP_CONTAINER"
  for rel_path in "${backend_files[@]}"; do
    remote_path="$REMOTE_DIR/$rel_path"
    backend_target="$APP_CONTAINER:$APP_BACKEND_DIR/${rel_path#backend/}"
    remote_path_quoted="$(shell_quote "$remote_path")"
    backend_target_quoted="$(shell_quote "$backend_target")"
    remote_sh "docker cp $remote_path_quoted $backend_target_quoted"
  done
  remote_sh "docker restart '$APP_CONTAINER' >/dev/null"
fi

if [[ "$needs_web_reload" == true ]]; then
  echo "Reloading web nginx ($WEB_CONTAINER)"
  remote_sh "docker exec '$WEB_CONTAINER' nginx -s reload >/dev/null 2>&1 || true"
fi

echo "Waiting for app health ($HEALTH_URL)"
remote_sh "for i in \$(seq 1 30); do if curl -fsS --max-time 5 '$HEALTH_URL' >/dev/null 2>&1; then exit 0; fi; sleep 2; done; exit 1"

echo "Hotfix publish complete."
