import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.auth_service import AuthService


@pytest.fixture
def auth_service():
    return AuthService()


@pytest.fixture
def mock_cursor():
    cursor = Mock()
    cursor.fetchone = Mock()
    return cursor


@pytest.fixture
def mock_conn(mock_cursor):
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    return conn


# Helper: simulate the INSERT raising a UNIQUE violation with a specific constraint.
def _make_unique_violation(constraint_name: str):
    import psycopg2

    class _FakeUniqueViolation(psycopg2.errors.UniqueViolation):
        @property
        def diag(self):
            return type("D", (), {"constraint_name": constraint_name})()

    return _FakeUniqueViolation()


@pytest.mark.asyncio
async def test_register_user_duplicate_email(auth_service, mock_conn, mock_cursor):
    # INSERT fails with the email UNIQUE constraint.
    mock_cursor.execute.side_effect = _make_unique_violation("users_email_key")

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn):
        with pytest.raises(ValueError, match="Email already registered"):
            await auth_service.register_user("user", "test@example.com", "Password1")


@pytest.mark.asyncio
async def test_register_user_duplicate_username(auth_service, mock_conn, mock_cursor):
    mock_cursor.execute.side_effect = _make_unique_violation("users_username_key")

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn):
        with pytest.raises(ValueError, match="Username already taken"):
            await auth_service.register_user("user", "fresh@example.com", "Password1")


@pytest.mark.asyncio
async def test_register_user_unique_violation_username_constraint(auth_service, mock_conn, mock_cursor):
    mock_cursor.execute.side_effect = _make_unique_violation("users_username_key")

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn):
        with pytest.raises(ValueError, match="Username already taken"):
            await auth_service.register_user("user", "fresh@example.com", "Password1")


@pytest.mark.asyncio
async def test_register_user_sql_injection_attempt(auth_service, mock_conn, mock_cursor):
    mock_cursor.fetchone.return_value = {"id": 1}

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), \
         patch("app.services.auth_service.psycopg2.connect", return_value=mock_conn), \
         patch("app.services.auth_service.create_access_token", return_value="token"):
        await auth_service.register_user("user", "test@example.com", "Password1")

        # The INSERT is the only execute call now (pre-check SELECTs were removed).
        insert_args = mock_cursor.execute.call_args_list[0][0]
        assert "%s" in insert_args[0]
        assert "INSERT INTO users" in insert_args[0]


@pytest.mark.asyncio
async def test_register_user_success(auth_service, mock_conn, mock_cursor):
    mock_cursor.fetchone.return_value = {"id": 1}

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), \
         patch("app.services.auth_service.psycopg2.connect", return_value=mock_conn), \
         patch("app.services.auth_service.create_access_token", return_value="token123"):
        result = await auth_service.register_user("testuser", "test@example.com", "Password1")

        assert result["access_token"] == "token123"
        assert result["user_id"] == 1
        assert result["tenant_db_name"] == "tenant_testuser"


@pytest.mark.asyncio
async def test_login_user_invalid_credentials(auth_service, mock_conn, mock_cursor):
    mock_cursor.fetchone.return_value = None

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn):
        with pytest.raises(ValueError, match="Invalid credentials"):
            await auth_service.login_user("test@example.com", "wrongpass")


@pytest.mark.asyncio
async def test_login_user_null_inputs(auth_service, mock_conn, mock_cursor):
    mock_cursor.fetchone.return_value = None

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn):
        with pytest.raises(ValueError, match="Invalid credentials"):
            await auth_service.login_user(None, None)
