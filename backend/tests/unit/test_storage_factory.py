import sys

import pytest

from app.config import settings
from app.storage import factory


@pytest.fixture(autouse=True)
def _reset():
    factory._reset_for_tests()
    yield
    factory._reset_for_tests()


def test_singleton_returns_same_instance(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "postgres")
    a = factory.get_storage()
    b = factory.get_storage()
    assert a is b


def test_postgres_selected_by_default(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "postgres")
    from app.storage.postgres import PostgresStorage

    assert isinstance(factory.get_storage(), PostgresStorage)


def test_sqlite_selected_without_importing_postgres(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "uh.db"))
    sys.modules.pop("app.storage.postgres", None)
    from app.storage.sqlite import SqliteStorage

    store = factory.get_storage()
    assert isinstance(store, SqliteStorage)
    assert "app.storage.postgres" not in sys.modules  # proves lazy import


def test_sqlite_without_path_raises(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "SQLITE_PATH", "")
    with pytest.raises(RuntimeError):
        factory.get_storage()
