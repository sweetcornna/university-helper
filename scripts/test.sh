#!/usr/bin/env bash
# Run backend / frontend / lint test suites against local sources (no docker required).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

TARGET="${1:-all}"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

run_backend() {
    echo "[test] backend pytest"
    pushd backend >/dev/null
    if [[ -x .venv/bin/python ]]; then
        .venv/bin/python -m pytest -q
    else
        python -m pytest -q
    fi
    popd >/dev/null
    echo -e "${GREEN}backend ok${NC}"
}

run_frontend() {
    echo "[test] frontend vitest"
    pushd frontend >/dev/null
    npm run test -- --run
    popd >/dev/null
    echo -e "${GREEN}frontend ok${NC}"
}

run_lint() {
    echo "[test] lint"
    pushd backend >/dev/null
    if [[ -x .venv/bin/ruff ]]; then
        .venv/bin/ruff check app/
        .venv/bin/ruff format --check app/
    else
        ruff check app/
        ruff format --check app/
    fi
    popd >/dev/null
    pushd frontend >/dev/null
    npm run lint
    popd >/dev/null
    echo -e "${GREEN}lint ok${NC}"
}

case "$TARGET" in
    backend)  run_backend ;;
    frontend) run_frontend ;;
    lint)     run_lint ;;
    all)      run_lint && run_backend && run_frontend ;;
    *)
        echo -e "${RED}Usage: $0 {backend|frontend|lint|all}${NC}" >&2
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}=== test pass ===${NC}"
