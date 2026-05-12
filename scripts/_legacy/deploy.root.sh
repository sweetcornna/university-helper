#!/bin/bash
set -euo pipefail

SERVER="${EASY_LEARNING_SERVER:-}"
PROJECT_NAME="${EASY_LEARNING_PROJECT_NAME:-easy_learning}"
REMOTE_DIR="${EASY_LEARNING_REMOTE_DIR:-/opt/${PROJECT_NAME}}"
COMPOSE_FILE="${EASY_LEARNING_COMPOSE_FILE:-docker-compose.yml}"
DB_PASSWORD="${EASY_LEARNING_POSTGRES_PASSWORD:-change-this-db-password}"
SECRET_KEY="${EASY_LEARNING_SECRET_KEY:-$(openssl rand -hex 32)}"
SHUAKE_COMPAT_SECRET="${EASY_LEARNING_SHUAKE_COMPAT_SECRET:-}"
CORS_ORIGINS="${EASY_LEARNING_CORS_ORIGINS:-[\"http://localhost:3000\",\"http://localhost:5173\"]}"

if [[ -z "$SERVER" ]]; then
  echo "Missing EASY_LEARNING_SERVER. Example: export EASY_LEARNING_SERVER=root@example.com" >&2
  exit 1
fi

tmp_env="$(mktemp)"
trap 'rm -f "$tmp_env"' EXIT

cat > "$tmp_env" <<EOF
POSTGRES_PASSWORD=${DB_PASSWORD}
SECRET_KEY=${SECRET_KEY}
SHUAKE_COMPAT_SECRET=${SHUAKE_COMPAT_SECRET}
CORS_ORIGINS=${CORS_ORIGINS}
EOF

echo "Uploading project to ${SERVER}:${REMOTE_DIR}"
ssh "$SERVER" "mkdir -p '$REMOTE_DIR'"
rsync -avz \
  --exclude 'node_modules' \
  --exclude '.git' \
  --exclude 'dist' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '%TEMP%' \
  ./ "$SERVER:$REMOTE_DIR/"
scp "$tmp_env" "$SERVER:$REMOTE_DIR/.env"

echo "Starting deployment with ${COMPOSE_FILE}"
ssh "$SERVER" "cd '$REMOTE_DIR' && compose_cmd=\$(command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo 'docker compose') && \$compose_cmd -f '$COMPOSE_FILE' down || true"
ssh "$SERVER" "cd '$REMOTE_DIR' && compose_cmd=\$(command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo 'docker compose') && \$compose_cmd -f '$COMPOSE_FILE' up -d --build"
ssh "$SERVER" "cd '$REMOTE_DIR' && compose_cmd=\$(command -v docker-compose >/dev/null 2>&1 && echo docker-compose || echo 'docker compose') && \$compose_cmd -f '$COMPOSE_FILE' ps"

echo "Deployment finished."
