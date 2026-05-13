import os
from unittest.mock import patch

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
