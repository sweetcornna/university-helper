#!/bin/bash
set -euo pipefail
umask 077

PROJECT_DIR="${PROJECT_DIR:-/opt/easy_learning}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DOMAIN="${DOMAIN:-shuake.cornna.xyz}"
UPSTREAM_HOST="${UPSTREAM_HOST:-127.0.0.1}"
UPSTREAM_PORT="${UPSTREAM_PORT:-18082}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
NGINX_CONFIG_DIR="${NGINX_CONFIG_DIR:-/etc/nginx/sites-available}"

NEW_APP_CONTAINER="${NEW_APP_CONTAINER:-easy-learning-app}"
NEW_DB_CONTAINER="${NEW_DB_CONTAINER:-easy-learning-db}"
LEGACY_APP_CONTAINER="${LEGACY_APP_CONTAINER:-shuake-easy-learning-app}"
LEGACY_DB_CONTAINER="${LEGACY_DB_CONTAINER:-shuake-easy-learning-db}"
LEGACY_DB_VOLUME="${LEGACY_DB_VOLUME:-easy_learning_shuake-postgres-data}"

REMOVE_LEGACY_DB_CONTAINER="${REMOVE_LEGACY_DB_CONTAINER:-false}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd docker
require_cmd nginx

mkdir -p "$BACKUP_DIR"

TEMP_DIR=""
NGINX_CANDIDATE=""
legacy_backup_tmp=""

cleanup_temporary_files() {
  if [[ -n "$legacy_backup_tmp" ]]; then
    rm -f -- "$legacy_backup_tmp"
  fi
  if [[ -n "$NGINX_CANDIDATE" ]]; then
    rm -f -- "$NGINX_CANDIDATE"
  fi
  if [[ -n "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
}
trap cleanup_temporary_files EXIT

TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/server-finalize.XXXXXX")"
chmod 700 "$TEMP_DIR"

timestamp="$(date +%Y%m%d-%H%M%S)"
legacy_backup="$BACKUP_DIR/shuake-main_db-$timestamp.sql.gz"
legacy_backup_tmp="$(mktemp "$BACKUP_DIR/.shuake-main_db-$timestamp.sql.gz.XXXXXX")"
users_schema="$TEMP_DIR/users_schema.sql"
users_data="$TEMP_DIR/users_data.sql"
nginx_target="$NGINX_CONFIG_DIR/$DOMAIN"
nginx_backup="$NGINX_CONFIG_DIR/$DOMAIN.bak-$timestamp"

echo "[1/6] Backing up legacy database to $legacy_backup"
docker exec "$LEGACY_DB_CONTAINER" pg_dump -U easylearning -d main_db | gzip -c > "$legacy_backup_tmp"
gzip -t "$legacy_backup_tmp"
[[ -s "$legacy_backup_tmp" ]]
chmod 600 "$legacy_backup_tmp"
mv -f -- "$legacy_backup_tmp" "$legacy_backup"
legacy_backup_tmp=""
ls -lh "$legacy_backup"

echo "[2/6] Exporting users table from legacy database"
docker exec "$LEGACY_DB_CONTAINER" pg_dump -U easylearning -d main_db -t users --schema-only > "$users_schema"
docker exec "$LEGACY_DB_CONTAINER" pg_dump -U easylearning -d main_db -t users --data-only --column-inserts > "$users_data"

echo "[3/6] Ensuring users table exists in new database"
docker exec "$NEW_DB_CONTAINER" psql -U easylearning -d main_db <<'SQL'
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
SQL

users_exists="$(
  docker exec "$NEW_DB_CONTAINER" psql -U easylearning -d main_db -Atc \
    "select count(*) from information_schema.tables where table_schema='public' and table_name='users';"
)"
if [[ "$users_exists" == "0" ]]; then
  docker exec -i "$NEW_DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U easylearning -d main_db < "$users_schema"
fi

users_count="$(
  docker exec "$NEW_DB_CONTAINER" psql -U easylearning -d main_db -Atc "select count(*) from users;" 2>/dev/null || echo 0
)"
if [[ "$users_count" == "0" ]]; then
  echo "[4/6] Importing users data into new database"
  docker exec -i "$NEW_DB_CONTAINER" psql -v ON_ERROR_STOP=1 -U easylearning -d main_db < "$users_data"
else
  echo "[4/6] Skipping user import because target database already contains $users_count users"
fi

new_users="$(
  docker exec "$NEW_DB_CONTAINER" psql -U easylearning -d main_db -Atc "select count(*) from users;"
)"
old_users="$(
  docker exec "$LEGACY_DB_CONTAINER" psql -U easylearning -d main_db -Atc "select count(*) from users;"
)"
echo "New users: $new_users"
echo "Old users: $old_users"
if [[ "$new_users" != "$old_users" ]]; then
  echo "User migration verification failed: new=$new_users old=$old_users" >&2
  exit 1
fi

echo "[5/6] Repointing host Nginx for $DOMAIN to $UPSTREAM_HOST:$UPSTREAM_PORT"
cp "$nginx_target" "$nginx_backup"
NGINX_CANDIDATE="$(mktemp "$NGINX_CONFIG_DIR/.server.XXXXXX")"
cat > "$NGINX_CANDIDATE" <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    charset utf-8;

    location ^~ /.well-known/acme-challenge/ {
        allow all;
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;
    charset utf-8;

    ssl_certificate /etc/nginx/ssl/$DOMAIN.cer;
    ssl_certificate_key /etc/nginx/ssl/$DOMAIN.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    location /api/ {
        proxy_pass http://$UPSTREAM_HOST:$UPSTREAM_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /ws {
        proxy_pass http://$UPSTREAM_HOST:$UPSTREAM_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
    }

    location / {
        proxy_pass http://$UPSTREAM_HOST:$UPSTREAM_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
EOF

# Validate a complete temporary nginx configuration that includes the
# candidate.  This keeps the live vhost untouched until nginx accepts the
# exact file that will be installed.
nginx_include_path="${NGINX_CANDIDATE//\\/\\\\}"
nginx_include_path="${nginx_include_path//\"/\\\"}"
nginx_validation_conf="$(mktemp "$TEMP_DIR/nginx-validation.XXXXXX")"
cat > "$nginx_validation_conf" <<EOF
events {}
http {
    include "$nginx_include_path";
}
EOF
if ! nginx -t -c "$nginx_validation_conf"; then
  echo "Nginx validation failed; keeping the previous configuration" >&2
  exit 1
fi

mv -f -- "$NGINX_CANDIDATE" "$nginx_target"
NGINX_CANDIDATE=""
if ! systemctl reload nginx; then
  echo "Nginx reload failed; restoring the previous configuration" >&2
  mv -f -- "$nginx_backup" "$nginx_target"
  exit 1
fi

echo "[6/6] Cleaning up legacy application container"
docker rm -f "$LEGACY_APP_CONTAINER" >/dev/null 2>&1 || true

if [[ "$REMOVE_LEGACY_DB_CONTAINER" == "true" ]]; then
  echo "Removing legacy database container $LEGACY_DB_CONTAINER"
  docker rm -f "$LEGACY_DB_CONTAINER"
else
  echo "Keeping legacy database container $LEGACY_DB_CONTAINER"
fi

echo
echo "Cutover complete."
echo "Backup: $legacy_backup"
echo "Legacy volume retained: $LEGACY_DB_VOLUME"
echo "Nginx backup: $nginx_backup"
