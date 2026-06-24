#!/usr/bin/env bash
# Local bootstrap for university-helper. Idempotent.
set -euo pipefail

# Release this one-click installer targets. Bump alongside backend/app/main.py
# and frontend/package.json when cutting a new version.
APP_VERSION="1.3.0"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== university-helper · local setup (v${APP_VERSION}) ==="
case "$(uname -s)" in
  Darwin)
    echo "Platform: macOS detected. Docker Desktop or Colima is recommended."
    ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      echo "Platform: WSL detected. Use Docker Desktop with WSL integration enabled."
    else
      echo "Platform: Linux detected. Docker Engine + Compose v2 is recommended."
    fi
    ;;
  *)
    echo "Platform: unsupported shell environment. Use Linux/macOS Bash or Windows via WSL2."
    ;;
esac

command -v docker >/dev/null 2>&1 || { echo "docker is required"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 is required"; exit 1; }

if [[ ! -f .env ]]; then
    echo "Creating .env from .env.example…"
    cp .env.example .env
    echo "  -> edit .env (SECRET_KEY, POSTGRES_PASSWORD, CORS_ORIGINS, CREDENTIAL_ENCRYPTION_KEY) before 'make start'"
fi

if [[ -d backend ]]; then
    echo "Backend: installing dev deps…"
    pushd backend >/dev/null
    if [[ ! -d .venv ]]; then
        python3 -m venv .venv
    fi
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -r requirements.txt -r requirements-dev.txt >/dev/null
    popd >/dev/null
fi

if [[ -d frontend ]]; then
    echo "Frontend: installing npm deps…"
    pushd frontend >/dev/null
    if [[ -f package-lock.json ]]; then
        npm ci
    else
        npm install
    fi
    popd >/dev/null
fi

echo "Optional: enable pre-commit hooks with: pre-commit install"
echo "Run:        make start    # docker-compose stack"
echo "Tests:      make test     # backend + frontend"
echo "Server deploy: bash scripts/deploy_server.sh --host <server-ip> --domain <domain>"
echo "=== setup complete ==="
