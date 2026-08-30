import threading
from collections import deque
from unittest.mock import Mock, call, patch

import pytest

import app.db.session as session_mod
from app.db.session import get_db_session


@pytest.fixture(autouse=True)
def clear_tenant_pools():
    with session_mod._tenant_lock:
        session_mod.tenant_pools.clear()
    yield
    with session_mod._tenant_lock:
        session_mod.tenant_pools.clear()


def test_repeated_checkouts_share_pool_and_release_each_reference():
    name = "tenant_repeat"
    first_conn = object()
    second_conn = object()
    pool = Mock()
    pool.getconn.side_effect = [first_conn, second_conn]

    with patch.object(session_mod, "_build_tenant_pool", return_value=pool) as build_pool:
        assert session_mod._checkout_tenant(name) is first_conn
        assert session_mod._checkout_tenant(name) is second_conn

    build_pool.assert_called_once_with(name)
    assert session_mod.tenant_pools[name].in_use == 2

    session_mod._release_tenant(name, first_conn)
    assert session_mod.tenant_pools[name].in_use == 1

    session_mod._release_tenant(name, second_conn)
    assert session_mod.tenant_pools[name].in_use == 0
    assert pool.putconn.call_args_list == [call(first_conn), call(second_conn)]


def test_release_failure_closes_connection_and_leaves_pool_evictable(caplog):
    name = "tenant_returnerror"
    conn = Mock()
    pool = Mock()
    pool.putconn.side_effect = RuntimeError("return failed")
    session_mod.tenant_pools[name] = session_mod._TenantPoolEntry(pool, in_use=1)

    # Preserve the existing contract: return failures are logged, not raised.
    session_mod._release_tenant(name, conn)

    pool.putconn.assert_called_once_with(conn)
    conn.close.assert_called_once_with()
    assert session_mod.tenant_pools[name].in_use == 0
    assert "putconn failed for tenant tenant_returnerror" in caplog.text

    with session_mod._tenant_lock:
        session_mod._evict_if_idle_locked()
    assert name not in session_mod.tenant_pools
    pool.closeall.assert_called_once_with()


def test_release_failure_does_not_mask_session_error():
    name = "tenant_originalerror"
    original_error = ValueError("query failed")
    conn = Mock()
    pool = Mock()
    pool.getconn.return_value = conn
    pool.putconn.side_effect = RuntimeError("return failed")

    with patch.object(session_mod, "_build_tenant_pool", return_value=pool):
        with pytest.raises(ValueError) as raised:
            with get_db_session(db_name=name):
                raise original_error

    assert raised.value is original_error
    conn.rollback.assert_called_once_with()
    conn.close.assert_called_once_with()
    assert session_mod.tenant_pools[name].in_use == 0


def test_release_for_unknown_tenant_closes_connection_directly():
    conn = Mock()

    session_mod._release_tenant("tenant_unknown", conn)

    conn.close.assert_called_once_with()
    assert not session_mod.tenant_pools


class _EventPool:
    """Pool fake whose return can be held at a deterministic barrier."""

    def __init__(self, connections=(), *, block_putconn=False):
        self.connections = deque(connections)
        self.block_putconn = block_putconn
        self.putconn_started = threading.Event()
        self.allow_putconn = threading.Event()
        self.closed = threading.Event()
        self.events = []

    def getconn(self):
        return self.connections.popleft()

    def putconn(self, conn):
        self.events.append(("putconn-started", conn))
        self.putconn_started.set()
        if self.block_putconn and not self.allow_putconn.wait(timeout=2):
            raise AssertionError("test did not release the putconn barrier")
        if self.closed.is_set():
            raise RuntimeError("putconn called after closeall")
        self.events.append(("putconn-finished", conn))

    def closeall(self):
        self.events.append(("closeall", None))
        self.closed.set()


def test_release_keeps_pool_live_until_putconn_finishes(monkeypatch):
    """Eviction must not close a pool while its final conn is being returned."""
    active_name = "tenant_active"
    next_name = "tenant_next"
    active_conn = object()
    next_conn = object()
    active_pool = _EventPool(block_putconn=True)
    next_pool = _EventPool([next_conn])
    checkout_finished = threading.Event()
    thread_errors = []

    session_mod.tenant_pools[active_name] = session_mod._TenantPoolEntry(active_pool, in_use=1)
    monkeypatch.setattr(session_mod, "MAX_TENANT_POOLS", 1)
    monkeypatch.setattr(session_mod, "_build_tenant_pool", lambda _name: next_pool)

    def release_active():
        try:
            session_mod._release_tenant(active_name, active_conn)
        except BaseException as exc:  # pragma: no cover - surfaced in main thread
            thread_errors.append(exc)

    def checkout_next():
        try:
            session_mod._checkout_tenant(next_name)
        except BaseException as exc:  # pragma: no cover - surfaced in main thread
            thread_errors.append(exc)
        finally:
            checkout_finished.set()

    release_thread = threading.Thread(target=release_active, daemon=True)
    checkout_thread = threading.Thread(target=checkout_next, daemon=True)
    try:
        release_thread.start()
        assert active_pool.putconn_started.wait(timeout=2)

        checkout_thread.start()
        assert checkout_finished.wait(timeout=2)

        # The old ordering published in_use=0 before putconn, so checkout_next
        # evicted this pool and closeall ran before this assertion.
        assert not active_pool.closed.is_set()
        assert session_mod.tenant_pools[active_name].in_use == 1

        active_pool.allow_putconn.set()
        release_thread.join(timeout=2)
        assert not release_thread.is_alive()
        assert not thread_errors
        assert session_mod.tenant_pools[active_name].in_use == 0

        with session_mod._tenant_lock:
            session_mod._evict_if_idle_locked()

        assert active_pool.events == [
            ("putconn-started", active_conn),
            ("putconn-finished", active_conn),
            ("closeall", None),
        ]

        session_mod._release_tenant(next_name, next_conn)
        assert session_mod.tenant_pools[next_name].in_use == 0
    finally:
        active_pool.allow_putconn.set()
        release_thread.join(timeout=2)
        checkout_thread.join(timeout=2)
