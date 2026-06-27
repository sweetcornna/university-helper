#!/usr/bin/env bash
# Build the frozen `uh-backend` sidecar (PyInstaller --onefile).
#
# Run from anywhere; resolves the repo root itself. Prereqs:
#   pip install -r backend/requirements.txt -r backend/requirements-dev.txt
#   a built frontend at frontend/dist (npm --prefix frontend ci && run build)
#
# Output:
#   dist/uh-backend       (Linux, macOS)
#   dist/uh-backend.exe   (Windows)
# CI (workstream F) renames it to frontend/src-tauri/binaries/uh-backend-<triple>[.exe].
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Use the project venv's python if present, else whatever `python` is on PATH.
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x backend/.venv/bin/python ]; then PY=backend/.venv/bin/python; else PY=python; fi
fi

# --add-data uses ';' as src:dst sep on Windows, ':' elsewhere. Allow override.
SEP="${PYI_ADDDATA_SEP:-}"
if [ -z "$SEP" ]; then
  case "${OSTYPE:-}${OS:-}" in
    *msys*|*cygwin*|*win32*|*Windows*) SEP=';' ;;
    *) SEP=':' ;;
  esac
fi

if [ ! -d frontend/dist ]; then
  echo "ERROR: frontend/dist missing — build the SPA first (npm --prefix frontend ci && npm --prefix frontend run build)" >&2
  exit 1
fi

"$PY" -m PyInstaller \
  --noconfirm --clean \
  --onefile \
  --name uh-backend \
  --paths backend \
  --collect-submodules app \
  --collect-submodules api \
  --collect-submodules Crypto \
  --collect-submodules fontTools \
  --collect-all lxml \
  --collect-all bcrypt \
  --hidden-import pyaes \
  --exclude-module psycopg2 \
  --add-data "frontend/dist${SEP}frontend/dist" \
  backend/desktop_entry.py

ls -l dist/uh-backend* 2>/dev/null || { echo "ERROR: no sidecar produced" >&2; exit 1; }
echo "Built sidecar: $(ls -1 dist/uh-backend*)"
