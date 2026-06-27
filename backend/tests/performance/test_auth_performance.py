import pytest
import time
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


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


class TestAuthPerformance:
    def test_login_response_time(self, client, mock_db):
        """Login should complete within acceptable time"""
        from app.core.security import hash_password
        mock_db.fetchone.return_value = {
            "id": 1,
            "password_hash": hash_password("Test1234"),
            "tenant_db_name": "tenant_test"
        }

        start = time.time()
        response = client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "Test1234"
        })
        duration = time.time() - start

        assert response.status_code == 200
        assert duration < 1.0

    def test_concurrent_logins(self, client, mock_db):
        """Handle concurrent login requests"""
        from app.core.security import hash_password
        mock_db.fetchone.return_value = {
            "id": 1,
            "password_hash": hash_password("Test1234"),
            "tenant_db_name": "tenant_test"
        }

        def login():
            return client.post("/api/v1/auth/login", json={
                "email": "test@example.com",
                "password": "Test1234"
            })

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(login) for _ in range(10)]
            results = [f.result() for f in futures]

        assert all(r.status_code == 200 for r in results)

    def test_register_response_time(self, client, mock_db):
        """Registration should complete within acceptable time"""
        with patch('psycopg2.connect'):
            mock_db.fetchone.side_effect = [None, {"id": 1}]

            start = time.time()
            response = client.post("/api/v1/auth/register", json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "Test1234"
            })
            duration = time.time() - start

            assert response.status_code == 201
            assert duration < 2.0
