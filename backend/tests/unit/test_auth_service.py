import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.auth_service import AuthService


@pytest.fixture
def auth_service():
    return AuthService()


@pytest.fixture
def mock_cursor():
    # Real psycopg2 cursors are context managers (closed on __exit__); mirror
    # that so `with conn.cursor() as cur:` works against the mock.
    cursor = MagicMock()
    cursor.fetchone = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
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
         patch("psycopg2.connect", return_value=mock_conn), \
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
         patch("psycopg2.connect", return_value=mock_conn), \
         patch("app.services.auth_service.create_access_token", return_value="token123"):
        result = await auth_service.register_user("testuser", "test@example.com", "Password1")

        assert result["access_token"] == "token123"
        assert result["user_id"] == 1
        assert result["tenant_db_name"] == "tenant_testuser"


def _make_ddl_mock(execute_side_effect):
    """Build a (conn, cursor, executed_log) triple for the DDL connection used
    by _create_tenant_database / _drop_tenant_database. Cursors are used as
    context managers, so __enter__ must return the same cursor."""
    ddl_conn = MagicMock()
    ddl_cur = MagicMock()
    ddl_cur.__enter__ = Mock(return_value=ddl_cur)
    ddl_cur.__exit__ = Mock(return_value=False)
    ddl_conn.cursor.return_value = ddl_cur
    executed = []

    def _exec(stmt, *args, **kwargs):
        # sql.SQL(...).format(...) renders against a real connection; the mock
        # conn supports as_string with a MagicMock arg, but fall back to str().
        try:
            text = stmt.as_string(ddl_conn)
        except Exception:
            text = str(stmt)
        executed.append(text)
        execute_side_effect(text, executed)

    ddl_cur.execute.side_effect = _exec
    return ddl_conn, ddl_cur, executed


@pytest.mark.asyncio
async def test_register_recovers_from_orphaned_tenant_db(auth_service, mock_conn, mock_cursor):
    """F07: an orphaned tenant DB (DuplicateDatabase on CREATE DATABASE) must not
    make a username permanently un-registerable — registration recreates it."""
    import psycopg2

    mock_cursor.fetchone.return_value = {"id": 1}

    def _effect(text, executed):
        # First CREATE DATABASE hits the orphan; after a DROP it succeeds.
        if "CREATE DATABASE" in text and sum("CREATE DATABASE" in e for e in executed) == 1:
            raise psycopg2.errors.DuplicateDatabase("database already exists")

    ddl_conn, _ddl_cur, executed = _make_ddl_mock(_effect)

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), \
         patch("psycopg2.connect", return_value=ddl_conn), \
         patch("app.services.auth_service.create_access_token", return_value="token"):
        result = await auth_service.register_user("bob", "bob@example.com", "Password1")

    assert result["tenant_db_name"] == "tenant_bob"
    joined = " ; ".join(executed)
    assert "DROP DATABASE" in joined, "orphaned tenant DB was not dropped before recreate"
    assert sum("CREATE DATABASE" in e for e in executed) >= 2, "tenant DB was not recreated after drop"


@pytest.mark.asyncio
async def test_register_rolls_back_user_and_drops_db_on_failure(auth_service, mock_conn, mock_cursor):
    """If tenant DB creation fails unrecoverably, the user row is rolled back AND
    any partially-created tenant DB is dropped (no orphan left behind)."""
    mock_cursor.fetchone.return_value = {"id": 42}

    def _effect(text, executed):
        if "CREATE DATABASE" in text:
            raise RuntimeError("boom after maybe-created")

    ddl_conn, _ddl_cur, executed = _make_ddl_mock(_effect)

    delete_calls = []
    orig_execute = mock_cursor.execute.side_effect

    def _track(stmt, *a, **k):
        if "DELETE FROM users" in str(stmt):
            delete_calls.append((stmt, a))
        if orig_execute is not None:
            return orig_execute(stmt, *a, **k)

    mock_cursor.execute.side_effect = _track

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), \
         patch("psycopg2.connect", return_value=ddl_conn), \
         patch("app.services.auth_service.create_access_token", return_value="token"):
        with pytest.raises(RuntimeError):
            await auth_service.register_user("carol", "carol@example.com", "Password1")

    assert delete_calls, "user row was not rolled back on tenant DB failure"
    assert any("DROP DATABASE" in e for e in executed), "partial tenant DB was not dropped on rollback"


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


@pytest.mark.asyncio
async def test_login_runs_bcrypt_even_when_user_missing(auth_service, mock_conn, mock_cursor):
    """User-enumeration timing oracle: a missing user must still incur a bcrypt
    verification against a dummy hash so the no-user branch and the wrong-password
    branch take comparable time."""
    mock_cursor.fetchone.return_value = None

    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), \
         patch("app.services.auth_service.verify_password", return_value=False) as mock_verify:
        with pytest.raises(ValueError, match="Invalid credentials"):
            await auth_service.login_user("nobody@example.com", "whatever")

        # verify_password MUST be invoked even though there is no matching row.
        assert mock_verify.called, "bcrypt verify was skipped for a nonexistent user (timing oracle)"


# --- provisioning failures map to actionable 503s instead of a bare 500 -------


def _pg_error(name: str):
    import psycopg2

    return getattr(psycopg2.errors, name)(name)


@pytest.mark.asyncio
@pytest.mark.parametrize("username", ["template", "postgres", "template1"])
async def test_register_rejects_reserved_usernames_before_any_db_call(auth_service, username):
    with patch("app.services.auth_service.get_db_session") as db, patch("psycopg2.connect") as connect:
        with pytest.raises(ValueError, match="保留"):
            await auth_service.register_user(username, f"{username}@example.com", "Password1")
    db.assert_not_called()
    connect.assert_not_called()


def test_template_database_is_never_created_or_dropped_directly():
    with patch("psycopg2.connect") as connect:
        with pytest.raises(ValueError):
            AuthService._create_tenant_database("tenant_template")
        AuthService._drop_tenant_database("tenant_template")
    connect.assert_not_called()


def test_object_in_use_is_retried_then_succeeds(monkeypatch):
    attempts = []

    def _effect(text, executed):
        if "CREATE DATABASE" in text:
            attempts.append(text)
            if len(attempts) < 3:
                raise _pg_error("ObjectInUse")

    ddl_conn, _cur, _executed = _make_ddl_mock(_effect)
    sleeps = []
    monkeypatch.setattr("app.services.auth_service.time.sleep", sleeps.append)

    with patch("psycopg2.connect", return_value=ddl_conn):
        AuthService._create_tenant_database("tenant_dave")

    assert len(attempts) == 3
    assert sleeps == [0.5, 1.0]


def test_object_in_use_exhausted_raises_503(monkeypatch):
    from app.core.exceptions import TenantProvisioningError

    def _effect(text, executed):
        if "CREATE DATABASE" in text:
            raise _pg_error("ObjectInUse")

    ddl_conn, _cur, _executed = _make_ddl_mock(_effect)
    monkeypatch.setattr("app.services.auth_service.time.sleep", lambda _s: None)

    with patch("psycopg2.connect", return_value=ddl_conn):
        with pytest.raises(TenantProvisioningError) as info:
            AuthService._create_tenant_database("tenant_erin")
    assert info.value.status_code == 503


def test_missing_template_maps_to_database_not_initialized():
    from app.core.exceptions import DatabaseNotInitializedError

    def _effect(text, executed):
        if "CREATE DATABASE" in text:
            raise _pg_error("InvalidCatalogName")

    ddl_conn, _cur, executed = _make_ddl_mock(_effect)
    with patch("psycopg2.connect", return_value=ddl_conn), patch.object(
        AuthService, "_heal_missing_template", return_value=False
    ):
        with pytest.raises(DatabaseNotInitializedError, match="tenant_template"):
            AuthService._create_tenant_database("tenant_frank")
    assert not any("DROP DATABASE" in e for e in executed)


def test_missing_template_is_healed_once_then_retried():
    calls = []

    def _effect(text, executed):
        if "CREATE DATABASE" in text:
            calls.append(text)
            if len(calls) == 1:
                raise _pg_error("InvalidCatalogName")

    ddl_conn, _cur, _executed = _make_ddl_mock(_effect)
    with patch("psycopg2.connect", return_value=ddl_conn), patch.object(
        AuthService, "_heal_missing_template", return_value=True
    ) as heal:
        AuthService._create_tenant_database("tenant_gina")
    heal.assert_called_once()
    assert len(calls) == 2


def test_insufficient_privilege_maps_to_503():
    from app.core.exceptions import TenantProvisioningError

    def _effect(text, executed):
        if "CREATE DATABASE" in text:
            raise _pg_error("InsufficientPrivilege")

    ddl_conn, _cur, _executed = _make_ddl_mock(_effect)
    with patch("psycopg2.connect", return_value=ddl_conn):
        with pytest.raises(TenantProvisioningError, match="CREATEDB"):
            AuthService._create_tenant_database("tenant_hank")


def test_unreachable_database_maps_to_503():
    import psycopg2

    from app.core.exceptions import TenantProvisioningError

    with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("could not connect")):
        with pytest.raises(TenantProvisioningError):
            AuthService._create_tenant_database("tenant_ivy")


@pytest.mark.asyncio
async def test_missing_users_table_maps_to_database_not_initialized(auth_service, mock_conn, mock_cursor):
    from app.core.exceptions import DatabaseNotInitializedError

    mock_cursor.execute.side_effect = _pg_error("UndefinedTable")
    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), patch(
        "psycopg2.connect"
    ) as connect:
        with pytest.raises(DatabaseNotInitializedError, match="users"):
            await auth_service.register_user("jack", "jack@example.com", "Password1")
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_provisioning_failure_still_rolls_back_user_row(auth_service, mock_conn, mock_cursor):
    from app.core.exceptions import TenantProvisioningError

    mock_cursor.fetchone.return_value = {"id": 7}
    with patch("app.services.auth_service.get_db_session", return_value=mock_conn), patch.object(
        AuthService, "_create_tenant_database", side_effect=TenantProvisioningError("busy")
    ), patch.object(AuthService, "_drop_tenant_database") as drop:
        with pytest.raises(TenantProvisioningError):
            await auth_service.register_user("kate", "kate@example.com", "Password1")
    assert any("DELETE FROM users" in str(c.args[0]) for c in mock_cursor.execute.call_args_list)
    drop.assert_called_once_with("tenant_kate")
