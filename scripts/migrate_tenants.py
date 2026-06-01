#!/usr/bin/env python3
"""Run the *tenant_db* alembic branch against every tenant database.

Alembic's default config only migrates one DB (the one in ALEMBIC_DB_URL /
MAIN_DB_*). Since this project uses one Postgres DB per user, schema changes
to `tenant_template` must be replayed against every existing `tenant_<name>`
DB on deploy. This script does that.

IMPORTANT — migration scoping (was a real bug, see audit F03/F08):
Migrations are split into two independent alembic branches:

  * `main_db`  branch (revisions 001, 002): users.email index + rate_limit_counters.
    These DDL statements reference the `users` table and ONLY belong in main_db.
  * `tenant_db` branch (revision t001 + descendants): todos / attachments /
    sessions. These belong in every tenant DB.

Running plain `alembic upgrade head` is intentionally ambiguous now (two heads).
This script targets `tenant_db@head` so it NEVER runs the main-DB migrations
(001/002) against tenant DBs — tenant DBs have no `users` table, so the old
`upgrade head` failed at revision 001 with `relation "users" does not exist`
and aborted the whole deploy. main_db is migrated separately with
`alembic upgrade main_db@head` (see scripts/setup.sh / the deploy path).

Usage (from inside the app container or with the backend venv active):

    python scripts/migrate_tenants.py
    python scripts/migrate_tenants.py --dry-run
    python scripts/migrate_tenants.py --only tenant_alice99,tenant_bob

Exits non-zero if any tenant migration fails. Skips tenants whose DB doesn't
exist (orphaned `users.tenant_db_name`) with a warning rather than crashing.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from typing import Iterable
from urllib.parse import quote

import psycopg2

logger = logging.getLogger("migrate_tenants")

# Alembic branch label whose head we migrate tenant DBs to. The main-DB
# migrations (001/002, branch label 'main_db') are deliberately excluded.
TENANT_BRANCH = "tenant_db"

# Must stay in sync with app/db/session.py:_TENANT_NAME_RE and the
# tenant_db_name format produced by auth_service (f"tenant_{username}",
# username constrained to [a-z0-9]+). Used to validate BOTH --only values and
# names read from the users table before they are interpolated into a DSN.
_TENANT_NAME_RE = re.compile(r"^tenant_[a-z0-9]+$")


def _validate_tenant_name(name: str) -> str:
    """Reject anything that is not a well-formed tenant DB name.

    Without this, a crafted `--only` value (e.g.
    `tenant_x?application_name=evil` or one containing `@`, `/`, whitespace)
    would be f-string-interpolated straight into the libpq connection URL and
    could alter the effective connection target (audit F42).
    """
    if not _TENANT_NAME_RE.match(name):
        raise SystemExit(
            f"invalid tenant database name: {name!r}. "
            "Tenant names must match ^tenant_[a-z0-9]+$"
        )
    return name


def _build_alembic_url(name: str) -> str:
    """Build the ALEMBIC_DB_URL for a single tenant DB.

    The name is validated against the tenant regex and every credential
    component is percent-quoted so passwords/usernames containing reserved URL
    characters (`@`, `:`, `/`, `?`, `#`, ...) cannot break out of their slot.
    """
    _validate_tenant_name(name)
    user = quote(_env("MAIN_DB_USER"), safe="")
    password = quote(_env("MAIN_DB_PASSWORD"), safe="")
    host = quote(_env("MAIN_DB_HOST", "localhost"), safe="")
    port = quote(_env("MAIN_DB_PORT", "5432"), safe="")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise SystemExit(f"missing required env var: {name}")
    return value


def _list_tenant_dbs() -> list[str]:
    conn = psycopg2.connect(
        host=_env("MAIN_DB_HOST", "localhost"),
        database=_env("MAIN_DB_NAME", "main_db"),
        user=_env("MAIN_DB_USER"),
        password=_env("MAIN_DB_PASSWORD"),
        port=int(_env("MAIN_DB_PORT", "5432")),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT tenant_db_name FROM users ORDER BY tenant_db_name")
            return [row[0] for row in cur.fetchall() if row[0]]
    finally:
        conn.close()


def _db_exists(name: str) -> bool:
    conn = psycopg2.connect(
        host=_env("MAIN_DB_HOST", "localhost"),
        database="postgres",
        user=_env("MAIN_DB_USER"),
        password=_env("MAIN_DB_PASSWORD"),
        port=int(_env("MAIN_DB_PORT", "5432")),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def _migrate_one(name: str, dry_run: bool) -> bool:
    url = _build_alembic_url(name)
    env = {**os.environ, "ALEMBIC_DB_URL": url}
    # Target ONLY the tenant_db branch head — never the main-DB migrations
    # (001/002), which reference a `users` table that tenant DBs do not have.
    cmd = ["alembic", "upgrade", f"{TENANT_BRANCH}@head"]
    if dry_run:
        cmd = ["alembic", "current"]
    logger.info("[%s] %s", name, " ".join(cmd))
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("[%s] failed: %s", name, result.stderr.strip())
        return False
    if result.stdout.strip():
        logger.info("[%s] %s", name, result.stdout.strip())
    return True


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="run `alembic current` instead of upgrade")
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="comma-separated tenant DB names to migrate (defaults to all known tenants)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.only:
        targets = [t.strip() for t in args.only.split(",") if t.strip()]
    else:
        targets = _list_tenant_dbs()

    # Validate EVERY target (CLI --only and DB-sourced names alike) before any
    # of them is interpolated into a connection URL (audit F42). Fail fast so a
    # single bad name aborts the run rather than silently building an off-target
    # DSN.
    for name in targets:
        _validate_tenant_name(name)

    if not targets:
        logger.warning("no tenants found — nothing to migrate")
        return 0

    failed: list[str] = []
    for name in targets:
        if not _db_exists(name):
            logger.warning("[%s] database missing in postgres — skipping", name)
            continue
        if not _migrate_one(name, dry_run=args.dry_run):
            failed.append(name)

    if failed:
        logger.error("FAILED tenants (%d): %s", len(failed), ", ".join(failed))
        return 1
    logger.info("ok: %d tenant(s) migrated", len(targets) - len(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
