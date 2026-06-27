import contextlib
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

# Set test environment variables before any imports
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_testing_only_min_32_chars")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    # base_url=http://localhost so TrustedHostMiddleware accepts the Host header
    return TestClient(app, base_url="http://localhost")


@pytest.fixture(autouse=True)
def reset_auth_rate_limiter():
    from app.middleware.rate_limiter import rate_limiter

    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def test_user():
    return {"username": "testuser", "email": "test@example.com", "password": "testpass123"}


@pytest.fixture
def mock_db_session():
    """Mock database session for integration tests"""
    with patch("app.db.session.get_db_session") as mock:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        mock.return_value = conn
        yield cur


@pytest.fixture
def auth_headers(client, mock_db_session):
    """Generate authentication headers with valid token"""
    from app.core.security import create_access_token

    token = create_access_token({"user_id": 1, "tenant_db_name": "tenant_test"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_chaoxing_client():
    """Mock Chaoxing client for course tests"""
    with patch("app.services.course.chaoxing.client.Chaoxing") as mock:
        instance = MagicMock()
        instance.login.return_value = {"status": True, "msg": "登录成功"}
        mock.return_value = instance
        yield instance


@pytest.fixture
def mock_redis():
    """Mock Redis client for caching tests"""
    with patch("redis.Redis") as mock:
        yield mock.return_value


@contextlib.contextmanager
def build_app(profile: str = "server", **env: str):
    """Yield a freshly-built ``app.main.app`` for the given PROFILE + env overrides.

    main.py constructs the FastAPI ``app`` (and decides the tenant_isolation guard +
    dependency_overrides) at IMPORT time — there is no app factory — so a test that
    wants PROFILE=local must reload the module with the env in place, then restore the
    default server-profile module afterwards so other tests are unaffected.
    """
    import app.config as config_mod
    import app.main as main_mod

    overrides = {"PROFILE": profile, **env}
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update({k: str(v) for k, v in overrides.items()})
    try:
        importlib.reload(config_mod)
        importlib.reload(main_mod)
        yield main_mod.app
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(config_mod)
        importlib.reload(main_mod)
