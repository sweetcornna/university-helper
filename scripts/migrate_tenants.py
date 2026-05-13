#!/usr/bin/env python3
"""Run `alembic upgrade head` against every tenant database.

Alembic's default config only migrates one DB (the one in ALEMBIC_DB_URL /
MAIN_DB_*). Since this project uses one Postgres DB per user, schema changes
to `tenant_template` must be replayed against every existing `tenant_<name>`
DB on deploy. This script does that.

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
import subprocess
import sys
from typing import Iterable

import psycopg2

logger = logging.getLogger("migrate_tenants")


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
    url = (
        f"postgresql+psycopg2://{_env('MAIN_DB_USER')}:{_env('MAIN_DB_PASSWORD')}"
        f"@{_env('MAIN_DB_HOST', 'localhost')}:{_env('MAIN_DB_PORT', '5432')}/{name}"
    )
    env = {**os.environ, "ALEMBIC_DB_URL": url}
    cmd = ["alembic", "upgrade", "head"]
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
