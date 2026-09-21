import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def mock_db():
    with patch("app.services.auth_service.get_db_session") as mock:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn
        yield cur


class TestAuthPerformance:
    def test_login_response_time(self, client, mock_db):
        """Login should complete within acceptable time."""
        from app.core.security import hash_password

        mock_db.fetchone.return_value = {
            "id": 1,
            "password_hash": hash_password("Test1234"),
            "tenant_db_name": "tenant_test",
        }

        start = time.perf_counter()
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "Test1234"},
        )
        duration = time.perf_counter() - start

        assert response.status_code == 200
        assert duration < 1.0

    def test_concurrent_logins(self, client, mock_db):
        """Handle concurrent login requests after the rate-limit gate."""
        from app.core.security import hash_password

        mock_db.fetchone.return_value = {
            "id": 1,
            "password_hash": hash_password("Test1234"),
            "tenant_db_name": "tenant_test",
        }

        def login():
            return client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "Test1234"},
            )

        with patch("app.api.v1.auth.rate_limiter.check_rate_limit"):
            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(lambda _: login(), range(10)))

        assert all(response.status_code == 200 for response in results)

    def test_register_response_time(self, client, mock_db):
        """Registration should complete within acceptable time."""
        mock_db.fetchone.return_value = {"id": 1}
        with patch("app.services.auth_service.AuthService._create_tenant_database"):
            start = time.perf_counter()
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "username": "testuser",
                    "email": "test@example.com",
                    "password": "Test1234",
                },
            )
            duration = time.perf_counter() - start

        assert response.status_code == 201
        assert duration < 2.0
