#!/usr/bin/env bash
# Verify the cache policy served by the nginx:1.27-alpine runtime image.
#
# The fixture deliberately gives the favicon a stable root name while placing
# JavaScript/CSS under Vite-style content-hashed names. This catches accidental
# removal or reordering of the exact-match favicon exception.
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${NGINX_TEST_IMAGE:-nginx:1.27-alpine}"
# Keep the fixture under the shared workspace: Docker Desktop may not expose
# the host's /tmp mount to the Linux VM, while the repository is shared.
FIXTURE_DIR="$(mktemp -d "$ROOT_DIR/nginx/.cache-test.XXXXXX")"
CONTAINER_ID=""

cleanup() {
    if [[ -n "$CONTAINER_ID" ]]; then
        docker rm --force "$CONTAINER_ID" >/dev/null 2>&1 || true
    fi
    rm -rf "$FIXTURE_DIR"
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
    echo "error: docker is required for the nginx cache-header regression" >&2
    exit 127
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "error: curl is required for the nginx cache-header regression" >&2
    exit 127
fi

mkdir -p "$FIXTURE_DIR/assets"
cp "$ROOT_DIR/frontend/public/favicon.svg" "$FIXTURE_DIR/favicon.svg"
cp "$ROOT_DIR/frontend/public/site.webmanifest" "$FIXTURE_DIR/site.webmanifest"
cp "$ROOT_DIR/frontend/public/robots.txt" "$FIXTURE_DIR/sw.js"
cp "$ROOT_DIR/frontend/public/robots.txt" "$FIXTURE_DIR/registerSW.js"
cp "$ROOT_DIR/frontend/public/robots.txt" "$FIXTURE_DIR/assets/index-AbCd1234.js"
cp "$ROOT_DIR/frontend/public/robots.txt" "$FIXTURE_DIR/assets/index-AbCd1234.css"

CONTAINER_ID="$(
    docker run --detach \
        --publish 127.0.0.1::80 \
        --volume "$ROOT_DIR/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
        --volume "$ROOT_DIR/nginx/proxy_params.conf:/etc/nginx/proxy_params.conf:ro" \
        --volume "$ROOT_DIR/nginx/snippets/security_headers.conf:/etc/nginx/snippets/security_headers.conf:ro" \
        --volume "$FIXTURE_DIR:/usr/share/nginx/html:ro" \
        "$IMAGE"
)"
PORT="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "80/tcp") 0).HostPort}}' "$CONTAINER_ID")"
BASE_URL="http://127.0.0.1:${PORT}"

ready=0
for _ in $(seq 1 40); do
    if curl --fail --silent --show-error --head "$BASE_URL/favicon.svg" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.25
done
if [[ "$ready" -ne 1 ]]; then
    echo "error: nginx container did not become ready" >&2
    docker logs "$CONTAINER_ID" >&2 || true
    exit 1
fi

require_header() {
    local headers="$1"
    local pattern="$2"
    local label="$3"
    if ! grep --extended-regexp --ignore-case --quiet "$pattern" <<<"$headers"; then
        echo "error: missing ${label}" >&2
        echo "$headers" >&2
        exit 1
    fi
}

require_security_headers() {
    local headers="$1"
    require_header "$headers" '^X-Content-Type-Options:[[:space:]]*nosniff' \
        'X-Content-Type-Options: nosniff'
    require_header "$headers" '^X-Frame-Options:[[:space:]]*DENY' \
        'X-Frame-Options: DENY'
    require_header "$headers" '^Referrer-Policy:[[:space:]]*strict-origin-when-cross-origin' \
        'Referrer-Policy'
    require_header "$headers" '^Permissions-Policy:' 'Permissions-Policy'
    require_header "$headers" '^Strict-Transport-Security:' \
        'Strict-Transport-Security'
    require_header "$headers" '^Content-Security-Policy:' \
        'Content-Security-Policy'
}

favicon_headers="$(curl --fail --silent --show-error --head "$BASE_URL/favicon.svg")"
require_header "$favicon_headers" '^Cache-Control:[[:space:]]*no-cache' \
    '/favicon.svg no-cache'
if grep --extended-regexp --ignore-case --quiet \
    '^Cache-Control:.*immutable' <<<"$favicon_headers"; then
    echo "error: /favicon.svg unexpectedly received immutable caching" >&2
    echo "$favicon_headers" >&2
    exit 1
fi
require_security_headers "$favicon_headers"

for asset in index-AbCd1234.js index-AbCd1234.css; do
    asset_headers="$(curl --fail --silent --show-error --head "$BASE_URL/assets/$asset")"
    require_header "$asset_headers" '^Cache-Control:.*public.*immutable' \
        "/assets/$asset immutable"
    require_security_headers "$asset_headers"
done

echo "nginx static cache-header regression passed (${IMAGE})"
