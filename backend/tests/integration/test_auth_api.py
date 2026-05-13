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
