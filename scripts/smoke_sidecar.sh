#!/usr/bin/env bash
# CI gate: boot the frozen sidecar, wait for its port token, assert /health == 200.
# Usage: scripts/smoke_sidecar.sh [path-to-binary]   (default: dist/uh-backend[.exe])
set -uo pipefail

BIN="${1:-}"
if [ -z "$BIN" ]; then
  if [ -x dist/uh-backend ]; then BIN=dist/uh-backend; else BIN=dist/uh-backend.exe; fi
fi
[ -x "$BIN" ] || { echo "ERROR: sidecar binary not found/executable: $BIN" >&2; exit 1; }

OUT="$(mktemp)"
set -m                       # own process group so we can reap the onefile child
"$BIN" >"$OUT" 2>&1 &
PID=$!

cleanup() {
  kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  rm -f "$OUT"
}
trap cleanup EXIT

# 1) wait up to 90s for the single token line (onefile bootloader unpacks ~35MB
#    to a temp dir on every cold start, which can take ~15-20s before any output).
PORT=""
for _ in $(seq 1 900); do
  PORT="$(sed -n 's/^UH_BACKEND_LISTENING \([0-9][0-9]*\).*/\1/p' "$OUT" | head -n1)"
  [ -n "$PORT" ] && break
  kill -0 "$PID" 2>/dev/null || { echo "ERROR: sidecar exited early:" >&2; cat "$OUT" >&2; exit 1; }
  sleep 0.1
done
[ -n "$PORT" ] || { echo "ERROR: never saw UH_BACKEND_LISTENING token:" >&2; cat "$OUT" >&2; exit 1; }
echo "sidecar listening on port $PORT"

# 2) poll /health up to 60s for 200 (heavy frozen imports + app startup)
CODE=""
for _ in $(seq 1 600); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/health" || true)"
  [ "$CODE" = "200" ] && { echo "PASS: /health 200"; exit 0; }
  sleep 0.1
done
echo "ERROR: /health never returned 200 (last code: ${CODE:-none})" >&2
cat "$OUT" >&2
exit 1
