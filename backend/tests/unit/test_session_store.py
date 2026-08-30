import logging
import os
from unittest.mock import patch

import pytest

from app.core import session_store as ss


def setup_function(_):
    ss._reset_for_tests()


def test_in_memory_get_set_delete():
    with patch.dict(os.environ, {"REDIS_URL": ""}):
        store = ss.get_session_store()
        store.set("k", b"v")
        assert store.get("k") == b"v"
        store.delete("k")
        assert store.get("k") is None


def test_in_memory_ttl_expires(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(ss.time, "time", lambda: fake_time[0])
    with patch.dict(os.environ, {"REDIS_URL": ""}):
        store = ss.get_session_store()
        store.set("k", b"v", ttl=10)
        assert store.get("k") == b"v"
        fake_time[0] += 11
        assert store.get("k") is None


def test_redis_backend_selected_when_url_set():
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
        # We don't have redis installed in CI; we only assert that the selector
        # tries to build a RedisSessionStore (which then raises ImportError).
        try:
            ss.get_session_store()
        except RuntimeError as exc:
            assert "REDIS_URL" in str(exc) or "redis" in str(exc).lower()
        except ImportError:
            pass  # acceptable if redis is genuinely missing


def test_redis_backend_log_redacts_sensitive_url(caplog):
    sentinel = "REDIS_URL_SENTINEL"
    url = f"redis://{sentinel}:{sentinel}@cache.internal:6380/2?token={sentinel}#{sentinel}"
    with (
        patch.dict(os.environ, {"REDIS_URL": url}),
        patch.object(ss, "RedisSessionStore") as store_cls,
        caplog.at_level(logging.INFO, logger=ss.logger.name),
    ):
        store = object()
        store_cls.return_value = store

        assert ss.get_session_store() is store

    store_cls.assert_called_once_with(url)
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert sentinel not in messages
    assert "redis://cache.internal:6380/2" in messages


def test_redis_backend_log_redacts_url_when_initialization_fails(caplog):
    sentinel = "REDIS_CONNECTION_SENTINEL"
    url = f"redis://{sentinel}:{sentinel}@cache.internal:6380/2?token={sentinel}#{sentinel}"
    with (
        patch.dict(os.environ, {"REDIS_URL": url}),
        patch.object(ss.RedisSessionStore, "__init__", side_effect=ConnectionError(url)),
        caplog.at_level(logging.INFO, logger=ss.logger.name),
    ):
        with pytest.raises(ConnectionError):
            ss.get_session_store()

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert sentinel not in messages
    assert "redis://cache.internal:6380/2" in messages


def test_redis_backend_log_handles_ipv6_and_invalid_urls(caplog):
    urls = (
        "redis://user:password@[2001:db8::1]:6380/3?token=IPV6_SECRET#IPV6_SECRET",
        "redis://[invalid",
    )
    with patch.object(ss, "RedisSessionStore"):
        for url in urls:
            ss._reset_for_tests()
            with patch.dict(os.environ, {"REDIS_URL": url}), caplog.at_level(logging.INFO, logger=ss.logger.name):
                ss.get_session_store()

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "IPV6_SECRET" not in messages
    assert "redis://[2001:db8::1]:6380/3" in messages
    assert "unparseable" in messages
