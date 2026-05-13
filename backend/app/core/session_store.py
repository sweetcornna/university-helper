"""Process-shared session store.

Today's in-memory `ChaoxingSigninManager._clients`, `_qr_sessions`, and the
course adapter cache are all per-process. That forces uvicorn down to one
worker (see Dockerfile.server) and means a single backend restart drops
every live chaoxing login.

This module is the first step toward fixing that without rewriting the
existing managers in place. It exposes a tiny key/value façade:

    store = get_session_store()
    store.set("chaoxing:client:<user_id>", pickle.dumps(client), ttl=3600)
    raw = store.get("chaoxing:client:<user_id>")

Backends:
- `InMemorySessionStore` — default; no behavior change for current deploys.
- `RedisSessionStore` — used when REDIS_URL is set. Requires the `redis`
  package to be installed (we don't pin it yet because no caller uses this
  store; the lazy import below means imports won't break in CI).

Migration plan (not done in this commit — see CHANGELOG / ARCHITECTURE):
  1. Wrap `ChaoxingSigninManager._clients` reads/writes through this store.
  2. Verify in staging that a worker restart no longer drops sessions.
  3. Flip `--workers` in Dockerfile.server to `$(nproc)`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class SessionStore(Protocol):
    def get(self, key: str) -> Optional[bytes]: ...
    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None: ...
    def delete(self, key: str) -> None: ...


class InMemorySessionStore:
    """Thread-safe in-process fallback. No cross-process sharing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, tuple[bytes, Optional[float]]] = {}

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and time.time() > expires_at:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        expires_at = time.time() + ttl if ttl else None
        with self._lock:
            self._data[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


class RedisSessionStore:
    """Redis-backed store. Lazy-imports `redis` so the module stays importable
    without the dependency installed."""

    def __init__(self, url: str) -> None:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "REDIS_URL is set but the `redis` package is not installed. "
                "Add it to backend/requirements.txt before enabling."
            ) from exc
        self._client = redis.Redis.from_url(url, decode_responses=False)

    def get(self, key: str) -> Optional[bytes]:
        return self._client.get(key)

    def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        if ttl:
            self._client.setex(key, ttl, value)
        else:
            self._client.set(key, value)

    def delete(self, key: str) -> None:
        self._client.delete(key)


_store: Optional[SessionStore] = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """Singleton accessor. Picks Redis if REDIS_URL is set, else in-memory."""
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            url = (os.getenv("REDIS_URL") or "").strip()
            if url:
                logger.info("Session store backend: redis (%s)", url)
                _store = RedisSessionStore(url)
            else:
                logger.info("Session store backend: in-memory (fallback)")
                _store = InMemorySessionStore()
    return _store


def _reset_for_tests() -> None:
    """Reset singleton state. Tests-only."""
    global _store
    with _store_lock:
        _store = None
