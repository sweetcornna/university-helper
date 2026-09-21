"""Startup repair of the schema registration depends on (mocked psycopg2)."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import psycopg2
import pytest

from app.db import bootstrap

REPO_DATABASE = Path(__file__).resolve().parents[3] / "database"


class FakeDB:
    """Tiny in-memory stand-in for the pieces of Postgres bootstrap touches."""

    def __init__(self, users=True, template=True, is_template=True, template_schema=True):
        self.users = users
        self.template = template
        self.is_template = is_template
        self.template_schema = template_schema
        self.statements: list[tuple[str, str]] = []
        self.fail_apply_on: str | None = None

    def connect(self, **kwargs):
        database = kwargs["database"]
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        state = {"last": None}

        def execute(stmt, params=None):
            text = stmt if isinstance(stmt, str) else stmt.as_string(MagicMock())
            self.statements.append((database, text))
            if "to_regclass('public.users')" in text:
                state["last"] = (self.users,)
            elif "to_regclass('public.todos')" in text:
                state["last"] = (self.template_schema,)
            elif "FROM pg_database" in text:
                state["last"] = (self.is_template,) if self.template else None
            elif text.startswith("CREATE DATABASE"):
                self.template = True
                self.is_template = False
                self.template_schema = False
            elif text.startswith("DROP DATABASE"):
                self.template = False
            elif "IS_TEMPLATE" in text:
                self.is_template = True
            elif "CREATE TABLE" in text:
                if self.fail_apply_on == database:
                    raise RuntimeError("schema apply failed")
                if database == "tenant_template":
                    self.template_schema = True
                else:
                    self.users = True
            else:
                state["last"] = (True,)

        cur.execute.side_effect = execute
        cur.fetchone.side_effect = lambda: state["last"]
        return conn


def _identifier_sql(monkeypatch):
    # psycopg2.sql.Composed.as_string needs a real connection; render simply instead.
    from psycopg2 import sql

    monkeypatch.setattr(sql.Composed, "as_string", lambda self, ctx: "".join(_render(p) for p in self._wrapped))
    monkeypatch.setattr(sql.SQL, "as_string", lambda self, ctx: self._wrapped)


def _render(part):
    from psycopg2 import sql

    if isinstance(part, sql.Identifier):
        return part.strings[0]
    return part._wrapped if isinstance(part, sql.SQL) else str(part)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(psycopg2, "connect", db.connect)
    _identifier_sql(monkeypatch)
    monkeypatch.setattr(bootstrap.settings, "DB_BOOTSTRAP_SQL_DIR", str(REPO_DATABASE))
    bootstrap._invalidate_status()
    return db


def test_resolve_sql_dir_finds_repository_database_dir(monkeypatch):
    monkeypatch.setattr(bootstrap.settings, "DB_BOOTSTRAP_SQL_DIR", "")
    assert bootstrap.resolve_sql_dir() == REPO_DATABASE


def test_resolve_sql_dir_accepts_flat_image_layout(tmp_path, monkeypatch):
    (tmp_path / "00-schema.sql").write_text("--")
    (tmp_path / "tenant_template.sql").write_text("--")
    monkeypatch.setattr(bootstrap.settings, "DB_BOOTSTRAP_SQL_DIR", str(tmp_path))
    assert bootstrap.resolve_sql_dir() == tmp_path


def test_healthy_schema_is_left_alone(fake_db):
    assert bootstrap.bootstrap_once() == "ok"
    assert not any(t.startswith(("CREATE DATABASE", "DROP DATABASE", "ALTER DATABASE")) for _, t in fake_db.statements)


def test_missing_template_is_created_filled_and_marked(fake_db):
    fake_db.template = False
    assert bootstrap.bootstrap_once() == "ok"
    texts = [t for _, t in fake_db.statements]
    assert any(t.startswith("CREATE DATABASE tenant_template") for t in texts)
    assert any(db == "tenant_template" and "CREATE TABLE" in t for db, t in fake_db.statements)
    assert any("IS_TEMPLATE true" in t for t in texts)
    assert any("pg_advisory_unlock" in t for t in texts)


def test_existing_unmarked_template_is_only_marked(fake_db):
    fake_db.is_template = False
    assert bootstrap.bootstrap_once() == "ok"
    texts = [t for _, t in fake_db.statements]
    assert not any(t.startswith("CREATE DATABASE") for t in texts)
    assert any("IS_TEMPLATE true" in t for t in texts)


def test_missing_users_table_applies_main_schema(fake_db):
    fake_db.users = False
    assert bootstrap.bootstrap_once() == "ok"
    assert any(db == "main_db" and "CREATE TABLE IF NOT EXISTS users" in t for db, t in fake_db.statements)


def test_failed_template_schema_drops_only_what_it_created(fake_db):
    fake_db.template = False
    fake_db.fail_apply_on = "tenant_template"
    with pytest.raises(RuntimeError):
        bootstrap.ensure_tenant_template(REPO_DATABASE)
    texts = [t for _, t in fake_db.statements]
    assert any(t.startswith("DROP DATABASE") for t in texts)
    assert any("pg_advisory_unlock" in t for t in texts)


def test_failed_apply_on_existing_template_never_drops_it(fake_db):
    fake_db.template_schema = False
    fake_db.fail_apply_on = "tenant_template"
    with pytest.raises(RuntimeError):
        bootstrap.ensure_tenant_template(REPO_DATABASE)
    assert not any(t.startswith("DROP DATABASE") for _, t in fake_db.statements)


def test_retry_loop_waits_for_database_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg2.OperationalError("connection refused")
        return "ok"

    monkeypatch.setattr(bootstrap, "bootstrap_once", flaky)
    stop = threading.Event()
    assert bootstrap.run_bootstrap_with_retry(stop, retry_seconds=0) == "ok"
    assert calls["n"] == 3


def test_retry_loop_stops_on_permission_error(monkeypatch):
    def denied():
        raise psycopg2.errors.InsufficientPrivilege("permission denied to create database")

    monkeypatch.setattr(bootstrap, "bootstrap_once", denied)
    assert bootstrap.run_bootstrap_with_retry(threading.Event(), retry_seconds=0) == "unknown"


def test_retry_loop_respects_stop_event(monkeypatch):
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(bootstrap, "bootstrap_once", lambda: pytest.fail("should not run"))
    assert bootstrap.run_bootstrap_with_retry(stop) == "unknown"


def test_cached_status_reports_unknown_when_database_unreachable(monkeypatch):
    bootstrap._invalidate_status()
    monkeypatch.setattr(bootstrap, "check_schema", MagicMock(side_effect=psycopg2.OperationalError("down")))
    assert bootstrap.cached_schema_status() == "unknown"
    bootstrap._invalidate_status()
