#!/usr/bin/env bash
# Production hotfix publisher for university-helper.
#
# Two transport modes — try SSH key first, fall back to sshpass + password:
#   - Default (recommended): set SERVER_USER + SERVER_IP + SSH_KEY (or rely on
#     ssh-agent) and the script uses StrictHostKeyChecking=accept-new on the
#     first run, then matches a real known_hosts entry afterwards.
#   - Legacy: setting EASY_LEARNING_SERVER_PASSWORD enables sshpass; this is
#     supported only because some operators still drive deploys from CI runners
#     without configured keys, and is intentionally noisier so it gets fixed.
#
# Env vars (current EASY_LEARNING_* names kept for backward compatibility):
#   SERVER_IP / EASY_LEARNING_SERVER_IP   — required
#   SERVER_USER / EASY_LEARNING_SERVER_USER (default: root)
#   SSH_KEY                               — path to private key (optional)
#   EASY_LEARNING_SERVER_PASSWORD         — password (sshpass fallback only)
#
set -euo pipefail

SERVER_IP="${SERVER_IP:-${EASY_LEARNING_SERVER_IP:-}}"
SERVER_USER="${SERVER_USER:-${EASY_LEARNING_SERVER_USER:-root}}"
SERVER_PASSWORD="${EASY_LEARNING_SERVER_PASSWORD:-}"
REMOTE_DIR="${EASY_LEARNING_REMOTE_DIR:-/opt/easy_learning}"
COMPOSE_FILE="${EASY_LEARNING_COMPOSE_FILE:-docker-compose.yml}"

APP_CONTAINER="${EASY_LEARNING_APP_CONTAINER:-easy-learning-app}"
NGINX_CONTAINER="${EASY_LEARNING_NGINX_CONTAINER:-easy-learning-nginx}"
APP_PORT="${EASY_LEARNING_APP_PORT:-8002}"
HEALTH_HOST="${EASY_LEARNING_HEALTH_HOST:-shuake.cornna.xyz}"
SSH_KEY="${SSH_KEY:-}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$SERVER_IP" ]]; then
  echo "Missing SERVER_IP (or EASY_LEARNING_SERVER_IP)" >&2
  exit 1
fi

if [[ "$#" -eq 0 ]]; then
  echo "Usage: scripts/hotfix_publish.sh <file> [file...]" >&2
  exit 1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd ssh
require_cmd scp

if [[ -n "$SERVER_PASSWORD" && -z "$SSH_KEY" ]]; then
  echo "WARNING: using sshpass password auth — switch to SSH keys (set SSH_KEY)." >&2
  require_cmd sshpass
  SSH_BASE=(
    sshpass -p "$SERVER_PASSWORD"
    ssh
    -o StrictHostKeyChecking=accept-new
    -o PreferredAuthentications=password
    -o PubkeyAuthentication=no
    -o ConnectTimeout=10
    "${SERVER_USER}@${SERVER_IP}"
  )
  SCP_BASE=(
    sshpass -p "$SERVER_PASSWORD"
    scp
    -o StrictHostKeyChecking=accept-new
  )
else
  SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
  if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS+=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
  fi
  SSH_BASE=(ssh "${SSH_OPTS[@]}" "${SERVER_USER}@${SERVER_IP}")
  SCP_BASE=(scp "${SSH_OPTS[@]}")
fi

remote_sh() {
  "${SSH_BASE[@]}" "$@"
}

needs_app_restart=false
needs_app_rebuild=false
needs_nginx_rebuild=false

backend_files=()

for rel_path in "$@"; do
  abs_path="$ROOT_DIR/$rel_path"
  if [[ ! -f "$abs_path" ]]; then
    echo "File not found: $rel_path" >&2
    exit 1
  fi

  remote_dirname="$(dirname "$REMOTE_DIR/$rel_path")"
  remote_sh "mkdir -p '$remote_dirname'"
  "${SCP_BASE[@]}" "$abs_path" "${SERVER_USER}@${SERVER_IP}:$REMOTE_DIR/$rel_path"

  case "$rel_path" in
    backend/*)
      backend_files+=("$rel_path")
      needs_app_restart=true
      ;;
  esac

  case "$rel_path" in
    Dockerfile|backend/requirements.txt|backend/pyproject.toml|docker-compose.yml)
      needs_app_rebuild=true
      ;;
    frontend/*|nginx/nginx.conf|Dockerfile.nginx)
      needs_nginx_rebuild=true
      ;;
  esac
done

if [[ "$needs_app_rebuild" == true ]]; then
  echo "Rebuilding app image"
  remote_sh "cd '$REMOTE_DIR' && docker-compose -f '$COMPOSE_FILE' up -d --build app"
elif [[ "$needs_app_restart" == true ]]; then
  echo "Hot updating app container"
  for rel_path in "${backend_files[@]}"; do
    in_container="/app/backend/${rel_path#backend/}"
    remote_sh "docker cp '$REMOTE_DIR/$rel_path' '$APP_CONTAINER:$in_container'"
  done
  remote_sh "docker restart '$APP_CONTAINER' >/dev/null"
fi

if [[ "$needs_nginx_rebuild" == true ]]; then
  echo "Rebuilding nginx image"
  remote_sh "cd '$REMOTE_DIR' && docker-compose -f '$COMPOSE_FILE' build nginx && docker-compose -f '$COMPOSE_FILE' up -d nginx"
fi

echo "Waiting for app health"
remote_sh "for i in \$(seq 1 30); do if curl -fsS --max-time 5 -H 'Host: $HEALTH_HOST' http://127.0.0.1:$APP_PORT/health >/dev/null; then exit 0; fi; sleep 2; done; exit 1"

echo "Hotfix publish complete."
