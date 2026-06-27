#!/usr/bin/env bash
# Produce a dev placeholder `binaries/uh-backend-<host-triple>[.exe]` from dev-stub.py.
# CI does NOT use this — it renames the real PyInstaller output instead.
set -euo pipefail
cd "$(dirname "$0")/.."                       # → frontend/src-tauri
# `rustc --print host-tuple` needs Rust ≥1.84; fall back to parsing `rustc -vV`.
TRIPLE="$(rustc --print host-tuple 2>/dev/null || rustc -vV | sed -n 's/^host: //p')"
SRC="binaries/dev-stub.py"
case "$TRIPLE" in
  *windows*) DEST="binaries/uh-backend-${TRIPLE}.exe" ;;
  *)         DEST="binaries/uh-backend-${TRIPLE}"     ;;
esac
cp "$SRC" "$DEST"
chmod +x "$DEST"
echo "wrote $DEST"
