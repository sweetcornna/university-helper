#!/usr/bin/env bash
# scripts/set_version.sh — stamp ONE version (the git tag, minus a leading 'v')
# into every manifest so the tag stays the single source of truth. Idempotent;
# safe to run from any CWD; works with both GNU and BSD userlands.
#
#   usage: scripts/set_version.sh <version>     e.g. scripts/set_version.sh 1.4.0
#
# Files stamped (locked interface — keep in sync with the CI and the spec §10):
#   1. frontend/package.json                  (top-level "version")
#   2. backend/pyproject.toml                 ([project] version = "…")
#   3. backend/app/main.py                    (FastAPI(version="…"))
#   4. frontend/src-tauri/tauri.conf.json     (top-level "version")
#   5. frontend/src-tauri/Cargo.toml          ([package] version = "…")
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <version>   e.g. $0 1.4.0" >&2
  exit 2
fi

VERSION="${1#v}"   # tolerate a leading 'v' (e.g. the raw git ref)

# Validate semver-ish so a typo can't silently stamp garbage everywhere.
if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'; then
  echo "error: '$1' is not a valid semantic version (expected X.Y.Z)" >&2
  exit 2
fi

# Resolve repo root from THIS script's location, not the caller's CWD.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Portable in-place edit: render to a temp file, then move over the original.
edit_sed() {  # edit_sed <file> <sed -E expression>
  local f="$1" expr="$2" tmp
  tmp="$(mktemp)"
  sed -E "$expr" "$f" > "$tmp"
  mv "$tmp" "$f"
}

edit_json_version() {  # edit_json_version <file>  — set top-level .version
  local f="$1" tmp
  tmp="$(mktemp)"
  jq --arg v "$VERSION" '.version = $v' "$f" > "$tmp"
  mv "$tmp" "$f"
}

# 1) frontend/package.json
edit_json_version "$ROOT/frontend/package.json"

# 2) backend/pyproject.toml — only the line that starts with `version = ` (so
#    requires-python / target-version / python_version are never matched).
edit_sed "$ROOT/backend/pyproject.toml" \
  's/^version = "[^"]*"/version = "'"$VERSION"'"/'

# 3) backend/app/main.py — the FastAPI(version="…") line (leading indentation).
edit_sed "$ROOT/backend/app/main.py" \
  's/^( *version=")[^"]*(",)/\1'"$VERSION"'\2/'

# 4) frontend/src-tauri/tauri.conf.json
edit_json_version "$ROOT/frontend/src-tauri/tauri.conf.json"

# 5) frontend/src-tauri/Cargo.toml — version under [package] ONLY (a dependency
#    table's `version = "…"` must be left alone). Section-scoped with awk.
cargo_tmp="$(mktemp)"
awk -v v="$VERSION" '
  /^\[/ { in_pkg = ($0 == "[package]") }
  in_pkg && /^version[[:space:]]*=[[:space:]]*"/ { sub(/"[^"]*"/, "\"" v "\"") }
  { print }
' "$ROOT/frontend/src-tauri/Cargo.toml" > "$cargo_tmp"
mv "$cargo_tmp" "$ROOT/frontend/src-tauri/Cargo.toml"

echo "set_version: stamped ${VERSION} into 5 manifests"
