#!/usr/bin/env bash
# Postgres docker-entrypoint runs *.sql against $POSTGRES_DB only.
# We need the `tenant_template` database to exist as a separate database
# so per-user tenant DBs can be created via `CREATE DATABASE ... TEMPLATE tenant_template`.
#
# This script must run AFTER the .sql files above (lexicographic order),
# and creates+populates `tenant_template` if missing.

set -euo pipefail

DB="${POSTGRES_DB:-main_db}"
USER="${POSTGRES_USER:-postgres}"
TEMPLATE_SCHEMA="/docker-entrypoint-initdb.d/templates/tenant_template.sql"

echo "[bootstrap] ensuring tenant_template database exists…"

# CREATE DATABASE cannot run inside a transaction, and `IF NOT EXISTS` is not
# supported. Probe pg_database, create only if absent.
EXISTS=$(psql -tA -U "$USER" -d "$DB" -c "SELECT 1 FROM pg_database WHERE datname='tenant_template';")
if [[ "$EXISTS" != "1" ]]; then
    psql -v ON_ERROR_STOP=1 -U "$USER" -d "$DB" -c "CREATE DATABASE tenant_template;"
    echo "[bootstrap] created tenant_template."
else
    echo "[bootstrap] tenant_template already exists, skipping CREATE."
fi

if [[ -f "$TEMPLATE_SCHEMA" ]]; then
    echo "[bootstrap] applying tenant_template schema…"
    psql -v ON_ERROR_STOP=1 -U "$USER" -d tenant_template -f "$TEMPLATE_SCHEMA"
else
    echo "[bootstrap] WARNING: $TEMPLATE_SCHEMA not found; skipping."
fi

echo "[bootstrap] done."
