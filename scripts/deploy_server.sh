#!/usr/bin/env bash
# Guided one-click deploy for University Helper (Linux / macOS / WSL2).
#
# Brings the full stack up with Docker: writes or updates .env (random secrets
# on first run, existing secrets are kept), pulls the prebuilt images (or builds
# from source with --build), starts app + postgres + web, waits for health and
# prints the access URL. With --domain it also writes a host-nginx vhost template.
#
# Works from a git checkout, or on its own: when docker-compose.release.yml and
# database/ are not next to it, it downloads the matching source release first.
#
# Usage:
#   bash scripts/deploy_server.sh [options]
#   curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y
#
# Options:
#   --domain <fqdn>          Public domain; sets ENV=production + https CORS and
#                            writes a host-nginx template under deploy/nginx/.
#   --host <ip>              Public IP for plain-http access when you have no domain.
#   --port <port>            Host port the web container listens on (default: 8080).
#   --tag <tag>              Release to install (default: latest; e.g. 1.4.7 or v1.4.7).
#   --admin-email <emails>   Administrator email(s), comma separated. Administrators
#                            see new-version notices. Default: first registered user.
#   --allowed-hosts <list>   Extra hostnames/IPs the site is opened with, comma separated.
#   --build                  Build images from source instead of pulling from GHCR.
#   --no-tls                 With --domain, skip the nginx/TLS template.
#   -y, --yes                Assume "yes" for prompts (non-interactive).
#   -h, --help               Show this help.
#
# Environment: UH_INSTALL_DIR (download target, default ./university-helper),
#              UH_DEPLOY_OFFLINE=1 (never download).
set -euo pipefail

# Release CI stamps the tag into the copy attached to each GitHub release.
UH_BUNDLED_TAG=""

REPO_SLUG="sweetcornna/university-helper"
PROJECT="university-helper"
COMPOSE_FILE="docker-compose.release.yml"
IMAGE_NS="ghcr.io/sweetcornna"
DB_VOLUME="${PROJECT}_shuake-postgres-data"
# China mirror for the frontend build in --build mode; release CI uses the
# public npm registry on GitHub-hosted runners. Override with
# BUILD_NPM_REGISTRY= (empty) to use the default public registry.
BUILD_NPM_REGISTRY="${BUILD_NPM_REGISTRY-https://registry.npmmirror.com}"
# Dockerfile.server defaults to a China PyPI mirror; set this (for example to
# https://pypi.org/simple) when building elsewhere.
BUILD_PIP_INDEX_URL="${BUILD_PIP_INDEX_URL:-}"

DOMAIN=""
DOMAIN_PROVIDED="0"
HOST_IP=""
HTTP_PORT="8080"
PORT_PROVIDED="0"
APP_PORT="8000"
HTTP_BIND_HOST="127.0.0.1"
TAG="latest"
TAG_PROVIDED="0"
ADMIN_EMAILS=""
ADMIN_PROVIDED="0"
ALLOWED_HOSTS=""
ALLOWED_PROVIDED="0"
MODE="pull"   # pull | build
DO_TLS="1"
ASSUME_YES="0"
DOCKER=(docker)
DC=(docker compose)

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

usage() {
  cat <<'EOF'
Guided one-click deploy for University Helper (Linux / macOS / WSL2).

Usage:
  bash scripts/deploy_server.sh [options]
  curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y

Options:
  --domain <fqdn>          Public domain (ENV=production, https CORS, nginx template)
  --host <ip>              Public IP for plain-http access without a domain
  --port <port>            Host port for the web container (default 8080)
  --tag <tag>              Release to install (default latest)
  --admin-email <emails>   Administrator email(s), comma separated
  --allowed-hosts <list>   Extra hostnames/IPs the site is opened with
  --build                  Build images from source instead of pulling
  --no-tls                 With --domain, skip the nginx/TLS template
  -y, --yes                Non-interactive
  -h, --help               Show this help

Re-running is safe: secrets in .env are kept, options you pass are applied.
EOF
  exit 0
}

validate_domain() {
  local domain="$1" label
  local -a labels
  local LC_ALL=C

  # Keep the diagnostic constant: domain input may contain control characters.
  [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]] || \
    die "Invalid --domain: expected an ASCII FQDN (for example example.com)."
  (( ${#domain} <= 253 )) || \
    die "Invalid --domain: expected an ASCII FQDN (for example example.com)."

  IFS='.' read -r -a labels <<< "$domain"
  for label in "${labels[@]}"; do
    (( ${#label} <= 63 )) || \
      die "Invalid --domain: expected an ASCII FQDN (for example example.com)."
  done
}

require_value() {
  # require_value <option> <remaining-arg-count> <value>
  if [[ "$2" -lt 2 || -z "$3" || "$3" == -* ]]; then
    die "Missing value for $1 (try --help)"
  fi
}

validate_inputs() {
  local LC_ALL=C
  if [[ -n "$HOST_IP" && ! "$HOST_IP" =~ ^[A-Za-z0-9.:-]+$ ]]; then
    die "Invalid --host: expected an IP address or hostname."
  fi
  if [[ ! "$HTTP_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$HTTP_PORT < 1 || 10#$HTTP_PORT > 65535 )); then
    die "Invalid --port: expected a number between 1 and 65535."
  fi
  HTTP_PORT="$((10#$HTTP_PORT))"
  if [[ -n "$ADMIN_EMAILS" && ! "$ADMIN_EMAILS" =~ ^[A-Za-z0-9._%+@,\ -]+$ ]]; then
    die "Invalid --admin-email: expected one or more email addresses separated by commas."
  fi
  if [[ -n "$ADMIN_EMAILS" ]]; then
    local email
    local -a emails
    IFS=',' read -r -a emails <<< "${ADMIN_EMAILS// /}"
    for email in ${emails[@]+"${emails[@]}"}; do
      [[ "$email" =~ ^[^@]+@[^@]+\.[^@]+$ ]] || \
        die "Invalid --admin-email: expected one or more email addresses separated by commas."
    done
    ADMIN_EMAILS="${ADMIN_EMAILS// /}"
  fi
  if [[ -n "$ALLOWED_HOSTS" && ! "$ALLOWED_HOSTS" =~ ^[A-Za-z0-9.*:,\ -]+$ ]]; then
    die "Invalid --allowed-hosts: expected hostnames or IPs separated by commas."
  fi
  ALLOWED_HOSTS="${ALLOWED_HOSTS// /}"
}

normalize_image_tag() {
  local raw="${1:-latest}"
  if [[ "$raw" =~ ^v[0-9] ]]; then
    printf '%s' "${raw#v}"
  else
    printf '%s' "$raw"
  fi
}

# ---- locate (or download) the deployment files -----------------------------
is_complete_root() {
  [[ -f "$1/$COMPOSE_FILE" \
    && -f "$1/database/00-schema.sql" \
    && -f "$1/database/02-bootstrap-tenant-template.sh" \
    && -f "$1/database/templates/tenant_template.sql" ]]
}

resolve_repo_root() {
  local script_path="${BASH_SOURCE[0]:-}" script_dir="" candidate
  if [[ -n "$script_path" && -f "$script_path" ]]; then
    script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  fi
  local -a candidates=()
  if [[ -n "$script_dir" ]]; then
    candidates+=("$script_dir/.." "$script_dir")
  fi
  candidates+=("$PWD" "$PWD/university-helper")
  for candidate in "${candidates[@]}"; do
    if is_complete_root "$candidate"; then
      (cd "$candidate" && pwd)
      return 0
    fi
  done
  return 1
}

resolve_source_tag() {
  local tag="$TAG"
  if [[ "$TAG_PROVIDED" != "1" || "$tag" == "latest" ]]; then
    tag="$UH_BUNDLED_TAG"
  fi
  if [[ -z "$tag" ]]; then
    local effective
    effective="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/${REPO_SLUG}/releases/latest")" || \
      die "Could not look up the latest release on GitHub (no network?). Pass --tag or run from a git checkout."
    tag="${effective##*/}"
  fi
  [[ "$tag" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([-+.][0-9A-Za-z.-]+)?$ ]] || \
    die "Could not determine which release to download (got '${tag}'). Pass --tag, e.g. --tag 1.4.7."
  [[ "$tag" == v* ]] || tag="v${tag}"
  printf '%s' "$tag"
}

download_source() {
  # download_source <vTAG> <target dir>: unpack that release's source over target.
  local tag="$1" target="$2" archive
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([-+.][0-9A-Za-z.-]+)?$ ]] || \
    die "Could not determine which release to download (got '${tag}'). Pass --tag, e.g. --tag 1.4.7."
  command -v curl >/dev/null 2>&1 || die "curl is required to download University Helper."
  command -v tar >/dev/null 2>&1 || die "tar is required to unpack University Helper."
  mkdir -p "$target"
  archive="$(mktemp "${TMPDIR:-/tmp}/uh-source.XXXXXX")"
  if ! curl -fsSL "https://github.com/${REPO_SLUG}/archive/refs/tags/${tag}.tar.gz" -o "$archive"; then
    rm -f "$archive"
    die "Download failed: https://github.com/${REPO_SLUG}/archive/refs/tags/${tag}.tar.gz"
  fi
  # The archive never contains .env, so an existing configuration is kept.
  if ! tar -xzf "$archive" -C "$target" --strip-components=1; then
    rm -f "$archive"
    die "Could not unpack the downloaded source into ${target}."
  fi
  rm -f "$archive"
  printf '%s\n' "$tag" > "$target/.uh-source-tag"
  is_complete_root "$target" || die "The downloaded source is incomplete: ${COMPOSE_FILE} or database/ is missing."
  ok "Source ready in ${target}"
}

reexec_from() {
  # reexec_from <target dir> <vTAG> <original args...>: run the downloaded script.
  local target="$1" tag="$2"
  shift 2
  local -a next_args=()
  [[ $# -gt 0 ]] && next_args=("$@")
  if [[ "$TAG_PROVIDED" != "1" ]]; then
    next_args+=(--tag "$tag")
  fi
  export UH_BOOTSTRAPPED=1
  if [[ ! -t 0 ]] && { true < /dev/tty; } 2>/dev/null; then
    # Piped install (curl | bash): give prompts the terminal back.
    exec bash "$target/scripts/deploy_server.sh" ${next_args[@]+"${next_args[@]}"} < /dev/tty
  fi
  exec bash "$target/scripts/deploy_server.sh" ${next_args[@]+"${next_args[@]}"}
}

bootstrap_source() {
  # $@ = the original command-line arguments
  [[ "${UH_BOOTSTRAPPED:-0}" == "1" ]] && \
    die "The downloaded source is incomplete: ${COMPOSE_FILE} or database/ is missing."
  [[ "${UH_DEPLOY_OFFLINE:-0}" == "1" ]] && \
    die "${COMPOSE_FILE} and database/ were not found next to this script, and UH_DEPLOY_OFFLINE=1 forbids downloading them. Run the script from a full checkout."
  command -v curl >/dev/null 2>&1 || die "curl is required to download University Helper."

  local tag target
  tag="$(resolve_source_tag)"
  target="${UH_INSTALL_DIR:-$PWD/university-helper}"
  info "Deployment files not found here; downloading University Helper ${tag} into ${target} …"
  download_source "$tag" "$target"
  reexec_from "$target" "$tag" "$@"
}

refresh_source_if_outdated() {
  # refresh_source_if_outdated <repo root> <original args...>
  # Updating an install means new compose files and scripts as well as new
  # images. A directory this script downloaded (it has .uh-source-tag) is moved
  # to the requested release first; a git checkout is the user's to update.
  local root="$1" wanted="" current=""
  shift
  if [[ "$TAG_PROVIDED" == "1" && "$TAG" != "latest" ]]; then
    wanted="$TAG"
  elif [[ -n "$UH_BUNDLED_TAG" ]]; then
    wanted="$UH_BUNDLED_TAG"
  fi
  [[ -n "$wanted" ]] || return 0
  [[ "$wanted" == v* ]] || wanted="v${wanted}"

  if [[ ! -f "$root/.uh-source-tag" ]]; then
    if [[ -d "$root/.git" ]]; then
      local checkout_version
      checkout_version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$root/backend/pyproject.toml" 2>/dev/null | head -n 1)"
      if [[ -n "$checkout_version" && "v${checkout_version}" != "$wanted" ]]; then
        warn "This git checkout is version ${checkout_version}, but you asked for ${wanted}. Compose files and scripts come from the checkout; run 'git fetch --tags && git checkout ${wanted}' first to match them."
      fi
    fi
    return 0
  fi
  [[ "${UH_BOOTSTRAPPED:-0}" == "1" ]] && return 0

  current="$(tr -d '[:space:]' < "$root/.uh-source-tag")"
  [[ "$current" == "$wanted" ]] && return 0
  if [[ "${UH_DEPLOY_OFFLINE:-0}" == "1" ]]; then
    warn "UH_DEPLOY_OFFLINE=1: keeping the ${current} deployment files while deploying ${wanted} images."
    return 0
  fi
  info "Updating the deployment files in ${root} from ${current:-unknown} to ${wanted} …"
  download_source "$wanted" "$root"
  reexec_from "$root" "$wanted" "$@"
}

# ---- platform detection ---------------------------------------------------
detect_platform() {
  PLATFORM="other"
  case "$(uname -s)" in
    Darwin) PLATFORM="macos" ;;
    Linux)  if grep -qi microsoft /proc/version 2>/dev/null; then PLATFORM="wsl"; else PLATFORM="linux"; fi ;;
  esac
}

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

  if ! docker info >/dev/null 2>&1; then
    if [[ "$(id -u)" != "0" ]] && command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
      # Not in the docker group (typical right after get.docker.com). sudo resets
      # the environment, so keep the variables compose substitutes.
      # shellcheck disable=SC2054  # the commas belong to --preserve-env's list
      DOCKER=(sudo --preserve-env=UH_TAG,HTTP_BIND_HOST,HTTP_PORT,APP_PORT docker)
      warn "Using sudo for docker. To avoid this: sudo usermod -aG docker \"\$USER\", then log in again."
    elif [[ "$(id -u)" != "0" ]] && [[ -S /var/run/docker.sock ]]; then
      die "Docker is running but this user cannot use it. Run: sudo usermod -aG docker \"\$USER\", log out and back in, then re-run (or re-run this script with sudo)."
    else
      die "Docker is installed but the daemon is not reachable. Start Docker and re-run."
    fi
  fi

  if "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    DC=("${DOCKER[@]}" compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    if [[ "${DOCKER[0]}" == "sudo" ]]; then
      # shellcheck disable=SC2054  # the commas belong to --preserve-env's list
      DC=(sudo --preserve-env=UH_TAG,HTTP_BIND_HOST,HTTP_PORT,APP_PORT docker-compose)
    else
      DC=(docker-compose)
    fi
    warn "Using legacy docker-compose v1 binary."
  else
    die "Docker Compose v2 is required (docker compose). Install the compose plugin and re-run."
  fi
  ok "Docker $("${DOCKER[@]}" --version | awk '{print $3}' | tr -d ,) + ${DC[*]} ready"
}
dc() { "${DC[@]}" -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }

db_volume_exists() {
  "${DOCKER[@]}" volume inspect "$DB_VOLUME" >/dev/null 2>&1
}

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
env_get() {
  [[ -f .env ]] || return 0
  local line
  line="$(grep -E "^${1}=" .env | tail -n 1 || true)"
  printf '%s' "${line#*=}"
}

env_has() {
  [[ -f .env ]] && grep -qE "^${1}=" .env
}

env_set() {
  # Replace KEY=... in place (or append), keeping the file's inode and mode.
  local tmp
  tmp="$(umask 077 && mktemp .env.tmp.XXXXXX)"
  ENV_KEY="$1" ENV_VALUE="$2" awk '
    BEGIN { key = ENVIRON["ENV_KEY"]; value = ENVIRON["ENV_VALUE"]; done = 0 }
    index($0, key "=") == 1 { if (!done) { print key "=" value; done = 1 } next }
    { print }
    END { if (!done) print key "=" value }
  ' .env > "$tmp"
  cat "$tmp" > .env
  rm -f "$tmp"
}

is_placeholder() {
  [[ -z "$1" || "$1" == change-this* || "$1" == replace-with* ]]
}

default_cors() {
  if [[ -n "$DOMAIN" ]]; then
    printf '["https://%s"]' "$DOMAIN"
  elif [[ -n "$HOST_IP" ]]; then
    printf '["http://%s:%s"]' "$HOST_IP" "$HTTP_PORT"
  else
    printf '["http://localhost:%s","http://127.0.0.1:%s"]' "$HTTP_PORT" "$HTTP_PORT"
  fi
}

default_env_tag() {
  # plain-http IP origins are rejected under ENV=production
  if [[ -n "$DOMAIN" ]]; then printf 'production'; else printf 'dev'; fi
}

local_ipv4s() {
  hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | paste -sd, - 2>/dev/null || true
}

write_new_env() {
  command -v openssl >/dev/null 2>&1 || die "openssl is required to generate secrets (or pre-create .env yourself)."
  info "Generating .env with fresh secrets…"
  local env_tag cors
  env_tag="$(default_env_tag)"
  cors="$(default_cors)"
  if [[ -n "$DOMAIN" ]]; then
    :
  elif [[ -n "$HOST_IP" ]]; then
    warn "No --domain: deploying http-only on ${HOST_IP}:${HTTP_PORT} (ENV=dev). Use --domain for a hardened TLS setup."
  else
    warn "No --domain/--host: deploying for local access only (http://localhost:${HTTP_PORT})."
  fi
  if [[ "$ALLOWED_PROVIDED" != "1" && -n "$HOST_IP" ]]; then
    ALLOWED_HOSTS="$(local_ipv4s)"
  fi

  umask 077
  cat > .env <<EOF
# Generated by scripts/deploy_server.sh — do NOT commit. Secrets are random;
# back them up (losing CREDENTIAL_ENCRYPTION_KEY makes stored platform
# credentials unrecoverable, losing POSTGRES_PASSWORD locks you out of the data).
POSTGRES_PASSWORD=$(gen_hex 24)
SECRET_KEY=$(gen_hex 32)
SHUAKE_COMPAT_SECRET=
CREDENTIAL_ENCRYPTION_KEY=$(gen_fernet)
CORS_ORIGINS=${cors}
ALLOWED_HOSTS=${ALLOWED_HOSTS}
ADMIN_EMAILS=${ADMIN_EMAILS}
ENV=${env_tag}
APP_PORT=${APP_PORT}
HTTP_PORT=${HTTP_PORT}
HTTP_BIND_HOST=${HTTP_BIND_HOST}
EOF
  chmod 600 .env
  ok ".env written (ENV=${env_tag}, CORS=${cors})"
}

update_existing_env() {
  info "Updating existing .env (secrets are kept)…"
  local explicit_site="0" value
  [[ "$DOMAIN_PROVIDED" == "1" || -n "$HOST_IP" ]] && explicit_site="1"

  # Secrets: fill in what is missing, never rotate what works.
  value="$(env_get POSTGRES_PASSWORD)"
  if [[ -z "$value" ]]; then
    db_volume_exists && die "POSTGRES_PASSWORD is empty in .env but the database volume ${DB_VOLUME} already exists. Restore the password from your .env backup; a new one cannot open the existing data."
    command -v openssl >/dev/null 2>&1 || die "openssl is required to generate secrets."
    env_set POSTGRES_PASSWORD "$(gen_hex 24)"
    ok "Generated POSTGRES_PASSWORD."
  elif is_placeholder "$value"; then
    if db_volume_exists; then
      warn "POSTGRES_PASSWORD is still the example value; the existing database uses it, so it is kept. Change it inside Postgres first if you want to rotate it."
    else
      env_set POSTGRES_PASSWORD "$(gen_hex 24)"
      ok "Replaced the example POSTGRES_PASSWORD with a random one."
    fi
  fi

  value="$(env_get SECRET_KEY)"
  if is_placeholder "$value" || (( ${#value} < 32 )); then
    command -v openssl >/dev/null 2>&1 || die "openssl is required to generate secrets."
    env_set SECRET_KEY "$(gen_hex 32)"
    warn "SECRET_KEY was missing, an example value or too short; generated a new one (existing logins must sign in again)."
  fi

  value="$(env_get CREDENTIAL_ENCRYPTION_KEY)"
  if is_placeholder "$value"; then
    command -v openssl >/dev/null 2>&1 || die "openssl is required to generate secrets."
    env_set CREDENTIAL_ENCRYPTION_KEY "$(gen_fernet)"
    warn "Generated CREDENTIAL_ENCRYPTION_KEY. Back up .env: losing this key makes stored platform credentials unrecoverable."
  elif [[ ! "$value" =~ ^[A-Za-z0-9_-]{43}=$ ]]; then
    die "CREDENTIAL_ENCRYPTION_KEY in .env is not a valid Fernet key (44 characters of urlsafe base64). Fix it by hand; replacing it would make stored credentials unreadable."
  fi
  env_has SHUAKE_COMPAT_SECRET || env_set SHUAKE_COMPAT_SECRET ""

  # Network settings: options passed now win, otherwise keep what .env has.
  if [[ "$PORT_PROVIDED" == "1" || -z "$(env_get HTTP_PORT)" ]]; then
    env_set HTTP_PORT "$HTTP_PORT"
  else
    HTTP_PORT="$(env_get HTTP_PORT)"
  fi
  if [[ -z "$(env_get APP_PORT)" ]]; then
    env_set APP_PORT "$APP_PORT"
  else
    APP_PORT="$(env_get APP_PORT)"
  fi
  if [[ "$explicit_site" == "1" || -z "$(env_get HTTP_BIND_HOST)" ]]; then
    env_set HTTP_BIND_HOST "$HTTP_BIND_HOST"
  else
    HTTP_BIND_HOST="$(env_get HTTP_BIND_HOST)"
  fi
  if [[ "$explicit_site" == "1" || -z "$(env_get CORS_ORIGINS)" ]]; then
    env_set CORS_ORIGINS "$(default_cors)"
  fi
  if [[ "$explicit_site" == "1" || -z "$(env_get ENV)" ]]; then
    env_set ENV "$(default_env_tag)"
  fi
  if [[ "$ALLOWED_PROVIDED" == "1" ]]; then
    env_set ALLOWED_HOSTS "$ALLOWED_HOSTS"
  elif [[ -n "$HOST_IP" && -z "$(env_get ALLOWED_HOSTS)" ]]; then
    env_set ALLOWED_HOSTS "$(local_ipv4s)"
  elif ! env_has ALLOWED_HOSTS; then
    env_set ALLOWED_HOSTS ""
  fi
  if [[ "$ADMIN_PROVIDED" == "1" ]]; then
    env_set ADMIN_EMAILS "$ADMIN_EMAILS"
  elif ! env_has ADMIN_EMAILS; then
    env_set ADMIN_EMAILS "$ADMIN_EMAILS"
  fi
  ok ".env updated (ENV=$(env_get ENV), CORS=$(env_get CORS_ORIGINS))"
}

prompt_admin_email() {
  [[ "$ADMIN_PROVIDED" == "1" || "$ASSUME_YES" == "1" ]] && return 0
  [[ -t 0 ]] || return 0
  [[ -n "$(env_get ADMIN_EMAILS)" ]] && return 0
  local reply
  read -r -p "Administrator email (sees update notices; Enter = first registered user): " reply || true
  reply="${reply// /}"
  [[ -z "$reply" ]] && return 0
  ADMIN_EMAILS="$reply"
  ADMIN_PROVIDED="1"
  validate_inputs
}

validate_env() {
  local env_tag cors
  env_tag="$(env_get ENV)"
  cors="$(env_get CORS_ORIGINS)"
  if [[ "$env_tag" == "production" || "$env_tag" == "prod" ]]; then
    # Same rule as the app's startup check: plain-http origins need "localhost".
    if printf '%s' "$cors" | tr ',' '\n' | grep -E 'http://' | grep -v 'localhost' >/dev/null; then
      die "ENV=production requires https:// CORS_ORIGINS (found ${cors}). Re-run with --domain <your.domain>, or with --host <ip> for plain http."
    fi
  fi
}

reconcile_env() {
  if [[ ! -f .env ]]; then
    if db_volume_exists; then
      die "Found the database volume ${DB_VOLUME} but no .env. Restore the .env you backed up (it holds the database password and CREDENTIAL_ENCRYPTION_KEY); new secrets would lock you out of the existing data."
    fi
    write_new_env
  else
    update_existing_env
  fi
  prompt_admin_email
  if [[ "$ADMIN_PROVIDED" == "1" ]]; then
    env_set ADMIN_EMAILS "$ADMIN_EMAILS"
  fi
  validate_env
}

# ---- bring up the stack ---------------------------------------------------
show_start_failure() {
  warn "Containers:"
  dc ps || true
  warn "Recent logs:"
  dc logs --tail=80 app postgres || true
}

deploy() {
  if [[ "$MODE" == "build" ]]; then
    info "Building images from source (this can take a few minutes)…"
    local -a app_build_args=()
    if [[ -n "$BUILD_PIP_INDEX_URL" ]]; then
      app_build_args=(--build-arg "PIP_INDEX_URL=${BUILD_PIP_INDEX_URL}")
    fi
    "${DOCKER[@]}" build -f Dockerfile.server ${app_build_args[@]+"${app_build_args[@]}"} \
      -t "${IMAGE_NS}/university-helper-app:local" .
    "${DOCKER[@]}" build -f Dockerfile.web --build-arg "NPM_REGISTRY=${BUILD_NPM_REGISTRY}" \
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
  if ! HTTP_BIND_HOST="$HTTP_BIND_HOST" HTTP_PORT="$HTTP_PORT" APP_PORT="$APP_PORT" dc up -d; then
    show_start_failure
    die "The stack did not start. Fix the error above and re-run this script; .env and the database are kept."
  fi
}

# ---- health ---------------------------------------------------------------
http_ok() {
  if command -v curl >/dev/null 2>&1; then
    local status
    status="$(curl -fsS -o /dev/null -w '%{http_code}' "$1")" || return 1
    [[ "$status" =~ ^2[0-9]{2}$ ]]
  else
    wget -q -O /dev/null "$1"
  fi
}
wait_health() {
  local url="http://127.0.0.1:${HTTP_PORT}/health"
  info "Waiting for health at ${url} …"
  local _
  for _ in $(seq 1 60); do
    if http_ok "$url"; then ok "App is healthy."; return 0; fi
    sleep 2
  done
  warn "Health check did not pass within 120s. Inspect logs:"
  warn "  ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} logs --tail=80 app"
  return 1
}

check_schema() {
  # Registration needs the users table and tenant_template; /health reports both.
  command -v curl >/dev/null 2>&1 || return 0
  local body _
  for _ in $(seq 1 15); do
    body="$(curl -fsS "http://127.0.0.1:${HTTP_PORT}/health" 2>/dev/null || true)"
    case "$body" in
      *'"schema":"ok"'*)
        ok "Database ready for registration (users table + tenant_template)."
        return 0 ;;
      *'"schema":"missing_'*|*'"schema":"unknown"'*) sleep 2 ;;
      *) return 0 ;;   # older image without the schema field
    esac
  done
  warn "The database is not ready for registration yet: ${body}"
  warn "The app repairs this on start. If sign-up keeps failing, check:"
  warn "  ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} logs --tail=80 app postgres"
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
main() {
  local -a original_args=()
  [[ $# -gt 0 ]] && original_args=("$@")

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --domain)
        DOMAIN="${2:-}"
        DOMAIN_PROVIDED="1"
        if [[ $# -ge 2 ]]; then shift 2; else shift; fi
        ;;
      --host)        require_value "$1" "$#" "${2:-}"; HOST_IP="$2"; shift 2 ;;
      --port)        require_value "$1" "$#" "${2:-}"; HTTP_PORT="$2"; PORT_PROVIDED="1"; shift 2 ;;
      --tag)         require_value "$1" "$#" "${2:-}"; TAG="$2"; TAG_PROVIDED="1"; shift 2 ;;
      --admin-email) require_value "$1" "$#" "${2:-}"; ADMIN_EMAILS="$2"; ADMIN_PROVIDED="1"; shift 2 ;;
      --allowed-hosts) require_value "$1" "$#" "${2:-}"; ALLOWED_HOSTS="$2"; ALLOWED_PROVIDED="1"; shift 2 ;;
      --build)  MODE="build"; shift ;;
      --no-tls) DO_TLS="0"; shift ;;
      -y|--yes) ASSUME_YES="1"; shift ;;
      -h|--help) usage ;;
      *) die "Unknown option: $1 (try --help)" ;;
    esac
  done

  if [[ "$DOMAIN_PROVIDED" == "1" ]]; then
    validate_domain "$DOMAIN"
  fi
  validate_inputs

  if [[ -n "$HOST_IP" && -z "$DOMAIN" ]]; then
    HTTP_BIND_HOST="0.0.0.0"
  fi

  local repo_root
  if ! repo_root="$(resolve_repo_root)"; then
    bootstrap_source ${original_args[@]+"${original_args[@]}"}
  fi
  refresh_source_if_outdated "$repo_root" ${original_args[@]+"${original_args[@]}"}
  cd "$repo_root"

  RAW_TAG="$TAG"
  TAG="$(normalize_image_tag "$TAG")"
  if [[ "$TAG" != "$RAW_TAG" ]]; then
    warn "Normalizing release tag ${RAW_TAG} -> ${TAG} for GHCR image tags."
  fi

  detect_platform
  info "University Helper guided deploy — platform: ${PLATFORM}, mode: ${MODE}, tag: ${TAG}"

  ensure_docker
  reconcile_env
  deploy
  wait_health
  scaffold_tls
  check_schema

  echo
  ok "Deploy complete."
  if [[ -n "$DOMAIN" ]]; then
    echo "  Access:  https://${DOMAIN}  (after the nginx/certbot step above)"
  elif [[ -n "$HOST_IP" ]]; then
    echo "  Access:  http://${HOST_IP}:${HTTP_PORT}"
  else
    echo "  Access:  http://localhost:${HTTP_PORT}"
  fi
  local admins
  admins="$(env_get ADMIN_EMAILS)"
  echo "  Admin:   ${admins:-the first account that registers}"
  cat <<EOF
  Manage:  ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} ps
           ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} logs -f app
           ${DC[*]} -p ${PROJECT} -f ${COMPOSE_FILE} down
  Update:  bash scripts/deploy_server.sh --tag <new version> -y   (keeps .env and data)
  Backup:  AGE_RECIPIENT=age1... bash scripts/db_backup.sh   (also back up .env)
EOF
}

main "$@"
