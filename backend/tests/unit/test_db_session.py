import pytest
from unittest.mock import Mock, patch, MagicMock
from app.db.session import get_main_db_connection, get_tenant_db_connection, get_db_session


@patch('app.db.session._get_main_pool')
def test_get_main_db_connection(mock_pool):
    mock_conn = Mock()
    mock_pool.return_value.getconn.return_value = mock_conn

    conn = get_main_db_connection()

    assert conn == mock_conn
    mock_pool.return_value.getconn.assert_called_once()


@patch('app.db.session.ThreadedConnectionPool')
@patch('app.db.session.settings')
def test_get_tenant_db_connection(mock_settings, mock_pool_class):
    mock_settings.MAIN_DB_HOST = "localhost"
    mock_settings.MAIN_DB_USER = "user"
    mock_settings.MAIN_DB_PASSWORD = "pass"
    mock_settings.MAIN_DB_PORT = 5432

    mock_pool = Mock()
    mock_conn = Mock()
    mock_pool.getconn.return_value = mock_conn
    mock_pool_class.return_value = mock_pool

    conn = get_tenant_db_connection("tenant_testdb")

    assert conn == mock_conn
    mock_pool_class.assert_called_once()


@patch('app.db.session._get_main_pool')
def test_get_db_session_main(mock_pool):
    mock_conn = Mock()
    mock_pool.return_value.getconn.return_value = mock_conn

    with get_db_session() as conn:
        assert conn == mock_conn

    mock_conn.commit.assert_called_once()
    mock_pool.return_value.putconn.assert_called_once_with(mock_conn)


@patch('app.db.session._get_main_pool')
def test_get_db_session_rollback(mock_pool):
    mock_conn = Mock()
    mock_conn.commit.side_effect = Exception("DB error")
    mock_pool.return_value.getconn.return_value = mock_conn

    with pytest.raises(Exception):
        with get_db_session() as conn:
            pass

    mock_conn.rollback.assert_called_once()


def test_checkout_tenant_does_not_leak_in_use_when_getconn_raises():
    """If pool.getconn() raises (e.g. PoolError: pool exhausted), the tenant's
    in_use refcount must NOT remain permanently elevated, otherwise the pool
    becomes un-evictable (only in_use == 0 pools are evicted)."""
    import app.db.session as session_mod

    name = "tenant_leaktest"

    failing_pool = Mock()
    failing_pool.getconn.side_effect = Exception("connection pool exhausted")

    session_mod.tenant_pools.clear()
    try:
        with patch.object(session_mod, "_build_tenant_pool", return_value=failing_pool):
            with pytest.raises(Exception):
                session_mod._checkout_tenant(name)

            entry = session_mod.tenant_pools.get(name)
            assert entry is not None
            assert entry.in_use == 0, (
                f"in_use leaked to {entry.in_use} after getconn() raised"
            )
    finally:
        session_mod.tenant_pools.clear()


def test_get_db_session_tenant_releases_when_getconn_raises():
    """get_db_session(db_name=...) must not leak in_use if checkout fails."""
    import app.db.session as session_mod

    name = "tenant_leaktest2"
    failing_pool = Mock()
    failing_pool.getconn.side_effect = Exception("connection pool exhausted")

    session_mod.tenant_pools.clear()
    try:
        with patch.object(session_mod, "_build_tenant_pool", return_value=failing_pool):
            with pytest.raises(Exception):
                with get_db_session(db_name=name):
                    pass

            entry = session_mod.tenant_pools.get(name)
            assert entry is not None
            assert entry.in_use == 0
    finally:
        session_mod.tenant_pools.clear()
