import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def mock_db():
    with patch('app.services.auth_service.get_db_session') as mock:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        # Cursors are used as context managers (`with conn.cursor() as cur:`),
        # so __enter__ must return the same cursor the test configures.
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn
        yield cur


@pytest.fixture
def mock_tenant_db():
    with patch('app.services.auth_service.psycopg2.connect') as mock:
        yield mock


class TestAuthRegistration:
    def test_register_success(self, client, mock_db, mock_tenant_db):
        # INSERT RETURNING → id=1 (no pre-check SELECTs anymore)
        mock_db.fetchone.return_value = {"id": 1}

        response = client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "Test1234"
        })

        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user_id"] == 1

    def test_register_duplicate_email(self, client, mock_db):
        import psycopg2

        class _FakeUniqueViolation(psycopg2.errors.UniqueViolation):
            @property
            def diag(self):
                return type("D", (), {"constraint_name": "users_email_key"})()

        mock_db.execute.side_effect = _FakeUniqueViolation()

        response = client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "existing@example.com",
            "password": "Test1234"
        })

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    def test_register_weak_password(self, client):
        response = client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "weak"
        })

        # Pydantic field_validator on RegisterRequest rejects weak passwords
        # at the schema layer, which FastAPI surfaces as 422.
        assert response.status_code == 422

    def test_register_invalid_username(self, client):
        response = client.post("/api/v1/auth/register", json={
            "username": "test-user!",
            "email": "test@example.com",
            "password": "Test1234"
        })

        # Pydantic field_validator on RegisterRequest rejects usernames that
        # contain characters outside [a-z0-9] (so the tenant database name
        # stays valid). FastAPI surfaces this as 422.
        assert response.status_code == 422
        assert "用户名" in response.text or "username" in response.text.lower()

    def test_register_rejects_over_72_byte_password(self, client, mock_db, mock_tenant_db):
        # 73 ASCII chars: passes the schema's 128-char cap but exceeds bcrypt's
        # 72-byte limit, so the service must reject it (400) rather than let
        # bcrypt silently truncate.
        mock_db.fetchone.return_value = {"id": 1}
        long_pw = "Aa1" + "x" * 70  # 73 chars, all lowercase/upper/digit present
        assert len(long_pw) == 73

        response = client.post("/api/v1/auth/register", json={
            "username": "longpwuser",
            "email": "longpw@example.com",
            "password": long_pw,
        })

        assert response.status_code == 400
        assert "72 bytes" in response.json()["detail"]

    def test_register_uppercase_username_rejected(self, client):
        # Regression: uppercase usernames used to pass schema validation and
        # the service-layer isalnum() check, then silently break every
        # subsequent tenant-scoped request because _validate_tenant_db_name
        # only accepts [a-z0-9]+. Now the schema rejects them up front.
        response = client.post("/api/v1/auth/register", json={
            "username": "TestUser",
            "email": "test@example.com",
            "password": "Test1234"
        })
        assert response.status_code == 422


class TestAuthLogin:
    def test_login_success(self, client, mock_db):
        from app.core.security import hash_password
        mock_db.fetchone.return_value = {
            "id": 1,
            "password_hash": hash_password("Test1234"),
            "tenant_db_name": "tenant_testuser"
        }

        response = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "Test1234"
        })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user_id"] == 1

    def test_login_invalid_credentials(self, client, mock_db):
        mock_db.fetchone.return_value = None

        response = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "WrongPass1"
        })

        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

    def test_login_wrong_password(self, client, mock_db):
        from app.core.security import hash_password
        mock_db.fetchone.return_value = {
            "id": 1,
            "password_hash": hash_password("Test1234"),
            "tenant_db_name": "tenant_testuser"
        }

        response = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "WrongPass1"
        })

        assert response.status_code == 401

    def test_login_error_does_not_echo_raw_value_error(self, client, mock_db):
        """The login handler must return a generic 401 message, never the raw
        ValueError text (info-leak guard)."""
        mock_db.fetchone.return_value = None

        # Force the service to raise a ValueError carrying sensitive-looking text.
        with patch(
            "app.api.v1.auth.auth_service.login_user",
            side_effect=ValueError("internal: user id 1234 secret detail"),
        ):
            response = client.post("/api/v1/auth/login", json={
                "email": "test@example.com",
                "password": "WhateverPass1",
            })

        assert response.status_code == 401
        detail = response.json()["detail"]
        assert "secret detail" not in detail
        assert "1234" not in detail
        assert detail == "Invalid credentials"


class TestShuakeToken:
    def test_shuake_token_non_numeric_user_id_returns_401_not_500(self):
        """F20: a validly-signed token whose user_id claim is non-numeric must
        yield a clean 401, not an int()-ValueError leaking to a 500."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.security import create_access_token

        # raise_server_exceptions=False so the global 500 handler is observable
        # (the bug: int('abc') ValueError escapes the endpoint -> 500).
        local_client = TestClient(
            app, base_url="http://localhost", raise_server_exceptions=False
        )
        token = create_access_token({"user_id": "abc", "tenant_db_name": "tenant_x"})

        response = local_client.get(
            "/api/v1/auth/shuake-token",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 401, (
            f"expected 401 for non-numeric user_id, got {response.status_code}"
        )
