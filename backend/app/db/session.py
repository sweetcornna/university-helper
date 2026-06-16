"""Database connection pools.

Architecture: one Postgres database per tenant (`tenant_<username>`). We hold:
- a single main-DB pool for the shared `users` table,
- an LRU map of per-tenant pools, capped at `MAX_TENANT_POOLS`.

Eviction rule: only pools with zero outstanding checkouts are evicted. This
prevents the previous race where `closeall()` could nuke a connection that
another thread was still using.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

main_pool: ThreadedConnectionPool | None = None


@dataclass
class _TenantPoolEntry:
    pool: ThreadedConnectionPool
    in_use: int = 0


# tenant_pools is LRU-ordered; `_tenant_lock` guards the map itself plus the
# `in_use` refcounts. ThreadedConnectionPool already serializes its own
# internal state so the outer lock only covers the map mutation window.
tenant_pools: OrderedDict[str, _TenantPoolEntry] = OrderedDict()
_tenant_lock = threading.Lock()
MAX_TENANT_POOLS = 100
_TENANT_NAME_RE = re.compile(r"^tenant_[a-z0-9]+$")


def _get_main_pool() -> ThreadedConnectionPool:
    global main_pool
    if main_pool is None:
        main_pool = ThreadedConnectionPool(
            minconn=5,
            maxconn=30,
            host=settings.MAIN_DB_HOST,
            database=settings.MAIN_DB_NAME,
            user=settings.MAIN_DB_USER,
            password=settings.MAIN_DB_PASSWORD,
            port=settings.MAIN_DB_PORT,
            cursor_factory=RealDictCursor,
        )
    return main_pool


def get_main_db_connection():
    return _get_main_pool().getconn()


def _validate_tenant_db_name(tenant_db_name: str) -> None:
    if not _TENANT_NAME_RE.match(tenant_db_name):
        raise ValueError(f"Invalid tenant database name: {tenant_db_name!r}. " "Must match pattern: tenant_[a-z0-9]+")


def _build_tenant_pool(tenant_db_name: str) -> ThreadedConnectionPool:
    return ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        host=settings.MAIN_DB_HOST,
        database=tenant_db_name,
        user=settings.MAIN_DB_USER,
        password=settings.MAIN_DB_PASSWORD,
        port=settings.MAIN_DB_PORT,
        cursor_factory=RealDictCursor,
    )


def _evict_if_idle_locked() -> None:
    """Caller must hold _tenant_lock. Drop the oldest *idle* pool.

    Walks the LRU map from oldest → newest and removes the first entry whose
    in-use counter is zero. If everything is busy, the cap is allowed to
    overflow briefly; we'd rather over-provision than nuke an in-flight
    connection.
    """
    for name, entry in list(tenant_pools.items()):
        if entry.in_use == 0:
            del tenant_pools[name]
            try:
                entry.pool.closeall()
            except Exception:  # pragma: no cover
                logger.exception("Failed to close evicted tenant pool %s", name)
            return
    logger.warning(
        "tenant pool cap reached (%d) but every pool is in use; allowing overflow",
        MAX_TENANT_POOLS,
    )


def _checkout_tenant(name: str):
    """Get a conn + increment refcount.

    The outer lock only covers map mutation + refcount bump; the actual
    `getconn()` call happens *outside* the lock because the underlying
    `ThreadedConnectionPool` has its own internal locking and we don't want
    one slow connect to serialize every other tenant's checkouts.
    """
    with _tenant_lock:
        entry = tenant_pools.get(name)
        if entry is None:
            while len(tenant_pools) >= MAX_TENANT_POOLS:
                before = len(tenant_pools)
                _evict_if_idle_locked()
                if len(tenant_pools) == before:
                    break  # nothing idle to evict; allow overflow
            entry = _TenantPoolEntry(pool=_build_tenant_pool(name))
            tenant_pools[name] = entry
        else:
            tenant_pools.move_to_end(name)
        entry.in_use += 1
        pool = entry.pool
    # getconn() outside the lock — see docstring. If it raises (e.g. PoolError
    # 'pool exhausted' or OperationalError when the tenant DB is briefly
    # unreachable) we MUST undo the in_use bump we made above; otherwise the
    # refcount leaks permanently and the pool can never be evicted
    # (_evict_if_idle_locked only drops pools with in_use == 0).
    try:
        return pool.getconn()
    except Exception:
        with _tenant_lock:
            current = tenant_pools.get(name)
            if current is entry:
                current.in_use = max(0, current.in_use - 1)
        raise


def _release_tenant(name: str, conn) -> None:
    with _tenant_lock:
        entry = tenant_pools.get(name)
        if entry is None:
            # Pool was evicted while we held the connection — close directly.
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass
            return
        entry.in_use = max(0, entry.in_use - 1)
        pool = entry.pool
    try:
        pool.putconn(conn)
    except Exception:  # pragma: no cover
        logger.exception("putconn failed for tenant %s", name)


def get_tenant_db_connection(tenant_db_name: str):
    _validate_tenant_db_name(tenant_db_name)
    return _checkout_tenant(tenant_db_name)


@contextmanager
def get_db_session(db_name: str | None = None):
    """Acquire a pooled connection; commit on success, rollback on error."""
    if db_name:
        _validate_tenant_db_name(db_name)
        conn = _checkout_tenant(db_name)
    else:
        conn = _get_main_pool().getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover
            logger.exception("rollback failed")
        raise
    finally:
        if db_name:
            _release_tenant(db_name, conn)
        else:
            _get_main_pool().putconn(conn)
