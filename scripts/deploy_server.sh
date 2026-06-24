#!/usr/bin/env bash
# Guided one-click deploy for University Helper (Linux / macOS / WSL2).
#
# Brings the full stack up with Docker: generates a hardened .env (random
# secrets), pulls the prebuilt images (or builds from source with --build),
# starts app + postgres + web, waits for health, and prints the access URL.
# Optionally scaffolds a host-nginx + Let's Encrypt vhost when a --domain is given.
#
# Usage:
#   bash scripts/deploy_server.sh [options]
#
# Options:
#   --domain <fqdn>   Public domain; sets ENV=production + https CORS, and writes
#                     a host-nginx vhost template under deploy/nginx/<fqdn>.conf.
#   --host <ip>       Public IP for plain-http access when you have no domain.
#   --port <port>     Host port the web container listens on (default: 8080).
#   --tag <tag>       Image tag to pull (default: latest; e.g. v1.3.0).
#   --build           Build images from source instead of pulling from GHCR.
#   --no-tls          With --domain, skip the nginx/TLS scaffolding step.
#   -y, --yes         Assume "yes" for prompts (non-interactive).
#   -h, --help        Show this help.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PROJECT="university-helper"
COMPOSE_FILE="docker-compose.release.yml"
IMAGE_NS="ghcr.io/sweetcornna"
# China mirror for the frontend build in --build mode; release CI uses the
# public npm registry on GitHub-hosted runners. Override with
# BUILD_NPM_REGISTRY= (empty) to use the default public registry.
BUILD_NPM_REGISTRY="${BUILD_NPM_REGISTRY:-https://registry.npmmirror.com}"

DOMAIN=""
HOST_IP=""
HTTP_PORT="8080"
APP_PORT="8000"
TAG="latest"
MODE="pull"   # pull | build
DO_TLS="1"
ASSUME_YES="0"

# ---- pretty logging -------------------------------------------------------
if [[ -t 1 ]]; then
  C_B="\033[1m"; C_G="\033[32m"; C_Y="\033[33m"; C_R="\033[31m"; C_0="\033[0m"
else
  C_B=""; C_G=""; C_Y=""; C_R=""; C_0=""
fi
info() { printf "${C_B}==>${C_0} %s\n" "$*"; }
ok()   { printf "${C_G}✓${C_0} %s\n" "$*"; }
warn() { printf "${C_Y}!${C_0} %s\n" "$*" >&2; }
die()  { printf "${C_R}✗ %s${C_0}\n" "$*" >&2; exit 1; }

confirm() {
  # confirm "question" -> 0 if yes
  [[ "$ASSUME_YES" == "1" ]] && return 0
  [[ -t 0 ]] || return 1   # no TTY and not -y => treat as "no"
  local reply
  read -r -p "$1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

usage() { sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# ---- arg parsing ----------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --host)   HOST_IP="${2:-}"; shift 2 ;;
    --port)   HTTP_PORT="${2:-}"; shift 2 ;;
    --tag)    TAG="${2:-}"; shift 2 ;;
    --build)  MODE="build"; shift ;;
    --no-tls) DO_TLS="0"; shift ;;
    -y|--yes) ASSUME_YES="1"; shift ;;
    -h|--help) usage ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# ---- platform detection ---------------------------------------------------
PLATFORM="other"
case "$(uname -s)" in
  Darwin) PLATFORM="macos" ;;
  Linux)  if grep -qi microsoft /proc/version 2>/dev/null; then PLATFORM="wsl"; else PLATFORM="linux"; fi ;;
esac
info "University Helper guided deploy — platform: ${PLATFORM}, mode: ${MODE}, tag: ${TAG}"

# ---- docker + compose -----------------------------------------------------
ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    if [[ "$PLATFORM" == "linux" ]] && confirm "Docker is not installed. Install it now via get.docker.com?"; then
      info "Installing Docker Engine…"
      curl -fsSL https://get.docker.com | sh
      sudo systemctl enable --now docker 2>/dev/null || true
    else
      case "$PLATFORM" in
        macos|wsl) die "Docker not found. Install Docker Desktop (https://docs.docker.com/desktop/) and re-run." ;;
        *)         die "Docker not found. Install Docker Engine (https://docs.docker.com/engine/install/) and re-run." ;;
      esac
    fi
  fi
  docker info >/dev/null 2>&1 || die "Docker is installed but the daemon is not reachable. Start Docker and re-run."

  if docker compose version >/dev/null 2>&1; then
    DC=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    DC=(docker-compose)
    warn "Using legacy docker-compose v1 binary."
  else
    die "Docker Compose v2 is required (docker compose). Install the compose plugin and re-run."
  fi
  ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) + ${DC[*]} ready"
}
dc() { "${DC[@]}" -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

# ---- secret generation ----------------------------------------------------
gen_hex()    { openssl rand -hex "${1:-32}" | tr -d '\n'; }
gen_fernet() {
  # A Fernet key is urlsafe-base64(os.urandom(32)) — exactly what this produces.
  if openssl rand -base64 32 2>/dev/null | tr '+/' '-_' | tr -d '\n' | grep -q .; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
  else
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" | tr -d '\n'
  fi
}

# ---- .env -----------------------------------------------------------------
ensure_env() {
  if [[ -f .env ]]; then
    ok "Existing .env kept (delete it to regenerate secrets)."
    return
  fi
  command -v openssl >/dev/null 2>&1 || die "openssl is required to generate secrets (or pre-create .env yourself)."
  info "Generating .env with fresh secrets…"

  local env_tag cors
  if [[ -n "$DOMAIN" ]]; then
    env_tag="production"
    cors="[\"https://${DOMAIN}\"]"
  elif [[ -n "$HOST_IP" ]]; then
    env_tag="dev"   # plain-http IP origins are rejected under ENV=production
    cors="[\"http://${HOST_IP}:${HTTP_PORT}\"]"
    warn "No --domain: deploying http-only on ${HOST_IP}:${HTTP_PORT} (ENV=dev). Use --domain for a hardened TLS setup."
  else
    env_tag="dev"
    cors="[\"http://localhost:${HTTP_PORT}\",\"http://127.0.0.1:${HTTP_PORT}\"]"
    warn "No --domain/--host: deploying for local access only (http://localhost:${HTTP_PORT})."
  fi

  umask 077
  cat > .env <<EOF
# Generated by scripts/deploy_server.sh — do NOT commit. Secrets are random;
# back them up (losing CREDENTIAL_ENCRYPTION_KEY makes stored platform
# credentials unrecoverable).
POSTGRES_PASSWORD=$(gen_hex 24)
SECRET_KEY=$(gen_hex 32)
SHUAKE_COMPAT_SECRET=
CREDENTIAL_ENCRYPTION_KEY=$(gen_fernet)
CORS_ORIGINS=${cors}
ENV=${env_tag}
APP_PORT=${APP_PORT}
HTTP_PORT=${HTTP_PORT}
EOF
  chmod 600 .env
  ok ".env written (ENV=${env_tag}, CORS=${cors})"
}

# ---- bring up the stack ---------------------------------------------------
deploy() {
  if [[ "$MODE" == "build" ]]; then
    info "Building images from source (this can take a few minutes)…"
    docker build -f Dockerfile.server -t "${IMAGE_NS}/university-helper-app:local" .
    docker build -f Dockerfile.web --build-arg "NPM_REGISTRY=${BUILD_NPM_REGISTRY}" \
      -t "${IMAGE_NS}/university-helper-web:local" .
    export UH_TAG="local"
  else
    export UH_TAG="$TAG"
    info "Pulling images ${IMAGE_NS}/university-helper-{app,web}:${UH_TAG}…"
    if ! dc pull; then
      warn "Pull failed (images may not be published yet, or no network)."
      confirm "Build from source instead?" || die "Aborting. Re-run with --build to build locally."
      MODE="build"; deploy; return
    fi
  fi
  info "Starting stack…"
  HTTP_PORT="$HTTP_PORT" APP_PORT="$APP_PORT" dc up -d
}

# ---- health ---------------------------------------------------------------
http_ok() {
  if command -v curl >/dev/null 2>&1; then curl -fsS -o /dev/null "$1"; else wget -q -O /dev/null "$1"; fi
}
wait_health() {
  local url="http://127.0.0.1:${HTTP_PORT}/health"
  info "Waiting for health at ${url} …"
  local i
  for i in $(seq 1 60); do
    if http_ok "$url"; then ok "App is healthy."; return 0; fi
    sleep 2
  done
  warn "Health check did not pass within 120s. Inspect logs:"
  warn "  ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} logs --tail=80 app"
  return 1
}

# ---- optional host nginx + TLS scaffolding --------------------------------
scaffold_tls() {
  [[ -n "$DOMAIN" && "$DO_TLS" == "1" ]] || return 0
  local conf="deploy/nginx/${DOMAIN}.conf"
  mkdir -p deploy/nginx
  cat > "$conf" <<EOF
# Host-nginx vhost for University Helper. Copy to your nginx (e.g.
# /etc/nginx/conf.d/${DOMAIN}.conf or sites-available), reload, then run certbot.
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${HTTP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }
}
EOF
  ok "Wrote host-nginx template: ${conf}"
  cat <<EOF

  To finish TLS on this host:
    sudo cp ${conf} /etc/nginx/conf.d/${DOMAIN}.conf   # (or sites-available + symlink)
    sudo nginx -t && sudo systemctl reload nginx
    sudo certbot --nginx -d ${DOMAIN}                  # obtains + installs the cert
EOF
}

# ---- run ------------------------------------------------------------------
ensure_docker
ensure_env
deploy
wait_health || true
scaffold_tls

echo
ok "Deploy complete."
if [[ -n "$DOMAIN" ]]; then
  echo "  Access:  https://${DOMAIN}  (after the nginx/certbot step above)"
elif [[ -n "$HOST_IP" ]]; then
  echo "  Access:  http://${HOST_IP}:${HTTP_PORT}"
else
  echo "  Access:  http://localhost:${HTTP_PORT}"
fi
cat <<EOF
  Manage:  ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} ps
           ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} logs -f app
           ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} down
  Backup:  AGE_RECIPIENT=age1... bash scripts/db_backup.sh
EOF
