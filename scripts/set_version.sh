#!/usr/bin/env bash
# scripts/set_version.sh — stamp ONE version (the git tag, minus a leading 'v')
# into every versioned release file so the tag stays the single source of truth. Idempotent;
# safe to run from any CWD; works with both GNU and BSD userlands.
#
#   usage: scripts/set_version.sh <version>     e.g. scripts/set_version.sh 1.4.0
#
# Files stamped (locked interface — keep in sync with the CI and the spec §10):
#   1. frontend/package.json                  (top-level "version")
#   2. frontend/package-lock.json             (top-level + root package version)
#   3. backend/pyproject.toml                 ([project] version = "…")
#   4. backend/app/main.py                    (FastAPI(version="…"))
#   5. frontend/src-tauri/tauri.conf.json     (top-level "version")
#   6. frontend/src-tauri/Cargo.toml          ([package] version = "…")
#   7. backend/uv.lock                         (editable root package version)
#   8. frontend/src-tauri/Cargo.lock           (uh-desktop root package version)
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

# 2) frontend/package-lock.json
if [[ -f "$ROOT/frontend/package-lock.json" ]]; then
  pkg_lock_tmp="$(mktemp)"
  jq --arg v "$VERSION" '.version = $v | .packages[""].version = $v' \
    "$ROOT/frontend/package-lock.json" > "$pkg_lock_tmp"
  mv "$pkg_lock_tmp" "$ROOT/frontend/package-lock.json"
fi

# 3) backend/pyproject.toml — only the line that starts with `version = ` (so
#    requires-python / target-version / python_version are never matched).
edit_sed "$ROOT/backend/pyproject.toml" \
  's/^version = "[^"]*"/version = "'"$VERSION"'"/'

# 4) backend/app/main.py — the FastAPI(version="…") line (leading indentation).
edit_sed "$ROOT/backend/app/main.py" \
  's/^( *version=")[^"]*(",)/\1'"$VERSION"'\2/'

# 5) frontend/src-tauri/tauri.conf.json
edit_json_version "$ROOT/frontend/src-tauri/tauri.conf.json"

# 6) frontend/src-tauri/Cargo.toml — version under [package] ONLY (a dependency
#    table's `version = "…"` must be left alone). Section-scoped with awk.
cargo_tmp="$(mktemp)"
awk -v v="$VERSION" '
  /^\[/ { in_pkg = ($0 == "[package]") }
  in_pkg && /^version[[:space:]]*=[[:space:]]*"/ { sub(/"[^"]*"/, "\"" v "\"") }
  { print }
' "$ROOT/frontend/src-tauri/Cargo.toml" > "$cargo_tmp"
mv "$cargo_tmp" "$ROOT/frontend/src-tauri/Cargo.toml"

# 7–8) Lockfiles — update only the project's own package section. The uv lock
#    root is identified by its editable source; Cargo's root package is
#    identified by its exact package name and lack of a registry source. Other
#    package/dependency versions (including same-name packages) remain intact.
edit_lock_package_version() {  # edit_lock_package_version <file> <name> [marker] [without-marker]
  local f="$1" package="$2" marker="${3:-}" without_marker="${4:-}" tmp
  tmp="$(mktemp)"
  awk -v target="$package" -v marker="$marker" -v without_marker="$without_marker" -v v="$VERSION" '
    function flush(    i) {
      if (is_target && (marker == "" || has_marker) &&
          (without_marker == "" || !has_without_marker)) {
        changed = 0
        for (i = 1; i <= n; i++) {
          if (!changed && lines[i] ~ /^version[[:space:]]*=[[:space:]]*"/) {
            sub(/"[^"]*"/, "\"" v "\"", lines[i])
            changed = 1
          }
          print lines[i]
        }
      } else {
        for (i = 1; i <= n; i++) print lines[i]
      }
      n = 0
      is_target = 0
      has_marker = 0
      has_without_marker = 0
    }
    /^\[\[package\]\]/ {
      if (n > 0) flush()
    }
    {
      lines[++n] = $0
      if ($0 == "name = \"" target "\"") is_target = 1
      if (marker != "" && $0 == marker) has_marker = 1
      if (without_marker != "" && index($0, without_marker) == 1) has_without_marker = 1
    }
    END {
      if (n > 0) flush()
    }
  ' "$f" > "$tmp"
  mv "$tmp" "$f"
}

if [[ -f "$ROOT/backend/uv.lock" ]]; then
  edit_lock_package_version "$ROOT/backend/uv.lock" \
    "university-helper-backend" 'source = { editable = "." }'
fi

if [[ -f "$ROOT/frontend/src-tauri/Cargo.lock" ]]; then
  edit_lock_package_version "$ROOT/frontend/src-tauri/Cargo.lock" "uh-desktop" "" 'source = '
fi

echo "set_version: stamped ${VERSION} into release files"
