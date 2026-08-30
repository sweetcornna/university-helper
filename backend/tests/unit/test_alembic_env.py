"""Regression tests for Alembic's environment URL construction."""

from __future__ import annotations

import configparser
import contextlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

ENV_SOURCE = Path(__file__).resolve().parents[2] / "alembic" / "env.py"


class _FakeAlembicConfig:
    config_ini_section = "alembic"
    config_file_name = None

    def __init__(self) -> None:
        self.file_config = configparser.ConfigParser()
        self.file_config.add_section(self.config_ini_section)

    def set_section_option(self, section: str, option: str, value: str) -> None:
        self.file_config.set(section, option, value)

    def get_section(self, section: str) -> dict[str, str]:
        return dict(self.file_config.items(section))


def _noop_configure(**_kwargs: object) -> None:
    return None


def _always_offline() -> bool:
    return True


@contextlib.contextmanager
def _transaction():
    yield


def _load_env_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    fake_context = types.ModuleType("alembic.context")
    fake_context.config = _FakeAlembicConfig()
    fake_context.is_offline_mode = _always_offline
    fake_context.configure = _noop_configure
    fake_context.begin_transaction = _transaction
    fake_context.run_migrations = _noop_configure

    fake_alembic = types.ModuleType("alembic")
    fake_alembic.context = fake_context
    monkeypatch.setitem(sys.modules, "alembic", fake_alembic)
    monkeypatch.setitem(sys.modules, "alembic.context", fake_context)

    spec = importlib.util.spec_from_file_location("alembic_env_test_module", ENV_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_db_url_round_trips_reserved_components(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_env_module(monkeypatch)
    monkeypatch.setenv("MAIN_DB_USER", "user@name:/?%#")
    monkeypatch.setenv("MAIN_DB_PASSWORD", "pass@word:/?%#")
    monkeypatch.setenv("MAIN_DB_HOST", "2001:db8::1")
    monkeypatch.setenv("MAIN_DB_PORT", "6543")
    monkeypatch.setenv("MAIN_DB_NAME", "database/name")
    monkeypatch.delenv("ALEMBIC_DB_URL", raising=False)

    parsed = make_url(module._db_url())

    assert parsed.drivername == "postgresql+psycopg2"
    assert parsed.username == "user@name:/?%#"
    assert parsed.password == "pass@word:/?%#"
    assert parsed.host == "2001:db8::1"
    assert parsed.port == 6543
    assert parsed.database == "database/name"


def test_db_url_can_be_written_through_configparser(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_env_module(monkeypatch)
    monkeypatch.setenv("MAIN_DB_USER", "postgres")
    monkeypatch.setenv("MAIN_DB_PASSWORD", "p%ss@word")
    monkeypatch.setenv("MAIN_DB_HOST", "localhost")
    monkeypatch.setenv("MAIN_DB_PORT", "5432")
    monkeypatch.setenv("MAIN_DB_NAME", "main_db")
    monkeypatch.delenv("ALEMBIC_DB_URL", raising=False)

    expected = module._db_url()
    config = _FakeAlembicConfig()
    module._set_sqlalchemy_url(config, expected)

    assert config.get_section(config.config_ini_section)["sqlalchemy.url"] == expected


def test_db_url_defaults_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_env_module(monkeypatch)
    monkeypatch.delenv("ALEMBIC_DB_URL", raising=False)
    for variable in (
        "MAIN_DB_USER",
        "MAIN_DB_PASSWORD",
        "MAIN_DB_HOST",
        "MAIN_DB_PORT",
        "MAIN_DB_NAME",
    ):
        monkeypatch.delenv(variable, raising=False)

    assert module._db_url() == "postgresql+psycopg2://postgres:@localhost:5432/main_db"
