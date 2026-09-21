"""Make sure the PostgreSQL schema that registration depends on exists.

Registration needs two things that are normally created by the Postgres
container's init scripts (database/*.sql + 02-bootstrap-tenant-template.sh):

- the ``users`` table in the main database, and
- the ``tenant_template`` database every tenant is cloned from.

Those scripts only run on a brand-new data volume, and they silently fail on
some machines (CRLF checkouts on Windows, a reused half-initialised volume, a
managed Postgres without the init mount). The server then passes ``/health``
while every registration returns 500. This module checks for both objects at
startup and recreates whatever is missing from the SQL files bundled with the
app, so a fresh install repairs itself instead of failing per request.

psycopg2 is imported lazily: the desktop build never uses Postgres.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

MAIN_SCHEMA_FILE = "00-schema.sql"
TENANT_TEMPLATE_FILE = "tenant_template.sql"
TEMPLATE_DB = "tenant_template"
# Arbitrary constant shared by every app process: serialises template repairs.
_ADVISORY_LOCK_KEY = 0x75686462
_CONNECT_TIMEOUT = 5
_STATUS_TTL_SECONDS = 60.0

_status_lock = threading.Lock()
_status_cache: tuple[float, str] | None = None


def resolve_sql_dir() -> Path | None:
    """Find the bundled schema files.

    Order: DB_BOOTSTRAP_SQL_DIR, then ``app/db/sql`` (copied in by
    Dockerfile.server), then the repository's ``database/`` directory.
    """
    here = Path(__file__).resolve()
    candidates = []
    if settings.DB_BOOTSTRAP_SQL_DIR:
        candidates.append(Path(settings.DB_BOOTSTRAP_SQL_DIR))
    candidates.append(here.parent / "sql")
    candidates.append(here.parents[3] / "database")
    for candidate in candidates:
        if _sql_file(candidate, MAIN_SCHEMA_FILE) and _sql_file(candidate, TENANT_TEMPLATE_FILE):
            return candidate
    return None


def _sql_file(directory: Path, name: str) -> Path | None:
    for path in (directory / name, directory / "templates" / name):
        if path.is_file():
            return path
    return None


def _connect(database: str):
    import psycopg2

    conn = psycopg2.connect(
        host=settings.MAIN_DB_HOST,
        database=database,
        user=settings.MAIN_DB_USER,
        password=settings.MAIN_DB_PASSWORD,
        port=settings.MAIN_DB_PORT,
        connect_timeout=_CONNECT_TIMEOUT,
    )
    conn.autocommit = True
    return conn


def _apply_sql(database: str, sql_path: Path) -> None:
    conn = _connect(database)
    try:
        with conn.cursor() as cur:
            # No parameters: psycopg2 sends the text verbatim, so `%` and `$$`
            # function bodies in the schema files are safe.
            cur.execute(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def check_schema() -> dict[str, bool]:
    conn = _connect(settings.MAIN_DB_NAME)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.users') IS NOT NULL")
            users_table = bool(_first(cur.fetchone()))
            cur.execute("SELECT datistemplate FROM pg_database WHERE datname = %s", (TEMPLATE_DB,))
            row = cur.fetchone()
    finally:
        conn.close()
    return {
        "users_table": users_table,
        "tenant_template": row is not None,
        "is_template": bool(row is not None and _first(row)),
    }


def _first(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def status_label(status: dict[str, bool]) -> str:
    if not status["users_table"]:
        return "missing_users"
    if not status["tenant_template"]:
        return "missing_tenant_template"
    return "ok"


def _template_has_schema() -> bool:
    conn = _connect(TEMPLATE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.todos') IS NOT NULL")
            return bool(_first(cur.fetchone()))
    finally:
        conn.close()


def ensure_main_schema(sql_dir: Path) -> None:
    schema = _sql_file(sql_dir, MAIN_SCHEMA_FILE)
    if schema is None:
        raise FileNotFoundError(f"{MAIN_SCHEMA_FILE} not found under {sql_dir}")
    logger.warning("users table is missing; applying %s to %s", schema.name, settings.MAIN_DB_NAME)
    _apply_sql(settings.MAIN_DB_NAME, schema)


def ensure_tenant_template(sql_dir: Path | None = None) -> None:
    """Create or repair ``tenant_template``. Safe to call from several processes."""
    from psycopg2 import errors as pg_errors
    from psycopg2 import sql

    sql_dir = sql_dir or resolve_sql_dir()
    template_sql = _sql_file(sql_dir, TENANT_TEMPLATE_FILE) if sql_dir else None
    if template_sql is None:
        raise FileNotFoundError(f"{TENANT_TEMPLATE_FILE} not found; cannot rebuild {TEMPLATE_DB}")

    conn = _connect(settings.MAIN_DB_NAME)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
            try:
                cur.execute("SELECT datistemplate FROM pg_database WHERE datname = %s", (TEMPLATE_DB,))
                row = cur.fetchone()
                created = False
                if row is None:
                    logger.warning("%s database is missing; creating it", TEMPLATE_DB)
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEMPLATE_DB)))
                    created = True
                if created or not _template_has_schema():
                    try:
                        _apply_sql(TEMPLATE_DB, template_sql)
                    except Exception:
                        if created:
                            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEMPLATE_DB)))
                        raise
                if row is None or not _first(row):
                    try:
                        cur.execute(
                            sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE true").format(sql.Identifier(TEMPLATE_DB))
                        )
                    except pg_errors.InsufficientPrivilege:
                        logger.warning("could not mark %s as IS_TEMPLATE (needs superuser); continuing", TEMPLATE_DB)
                logger.info("%s is ready", TEMPLATE_DB)
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
    finally:
        conn.close()
    _invalidate_status()


def bootstrap_once() -> str:
    status = check_schema()
    if status["users_table"] and status["tenant_template"] and status["is_template"]:
        return "ok"
    sql_dir = resolve_sql_dir()
    if sql_dir is None:
        logger.error(
            "Database schema incomplete (%s) and no bundled SQL files were found; "
            "run the deploy script again or apply database/*.sql by hand",
            status_label(status),
        )
        return status_label(status)
    if not status["users_table"]:
        ensure_main_schema(sql_dir)
    if not status["tenant_template"] or not status["is_template"]:
        ensure_tenant_template(sql_dir)
    return status_label(check_schema())


def run_bootstrap_with_retry(
    stop_event: threading.Event,
    retry_seconds: float = 5.0,
    max_wait_seconds: float = 300.0,
) -> str:
    """Retry while Postgres is still starting; give up on permission errors."""
    import psycopg2
    from psycopg2 import errors as pg_errors

    deadline = time.monotonic() + max_wait_seconds
    while not stop_event.is_set():
        try:
            label = bootstrap_once()
            _set_status(label)
            if label != "ok":
                logger.error("Database schema is still incomplete after bootstrap: %s", label)
            return label
        except pg_errors.InsufficientPrivilege:
            logger.error(
                "Database bootstrap needs CREATEDB (and ideally superuser) for %s; "
                "registration will fail until an administrator creates %s. "
                "数据库账号权限不足，无法自动创建 %s。",
                settings.MAIN_DB_USER,
                TEMPLATE_DB,
                TEMPLATE_DB,
            )
            return "unknown"
        except psycopg2.OperationalError as exc:
            if time.monotonic() >= deadline:
                logger.error("Database not reachable for schema bootstrap: %s", exc)
                return "unknown"
            logger.info("Database not ready for schema bootstrap yet (%s); retrying", exc)
            stop_event.wait(retry_seconds)
        except Exception:
            logger.exception("Database schema bootstrap failed")
            return "unknown"
    return "unknown"


def _set_status(label: str) -> None:
    global _status_cache
    with _status_lock:
        _status_cache = (time.monotonic(), label)


def _invalidate_status() -> None:
    global _status_cache
    with _status_lock:
        _status_cache = None


def cached_schema_status(ttl: float = _STATUS_TTL_SECONDS) -> str:
    """Schema label for /health, re-checked at most once per ``ttl`` seconds."""
    global _status_cache
    now = time.monotonic()
    with _status_lock:
        if _status_cache is not None and now - _status_cache[0] < ttl:
            return _status_cache[1]
    try:
        label = status_label(check_schema())
    except Exception:
        label = "unknown"
    _set_status(label)
    return label
