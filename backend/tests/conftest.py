import contextlib
import importlib
import os
from unittest.mock import MagicMock, patch

import pytest

# Set test environment variables before any application imports.
# These duplicate the `env =` block in pytest.ini on purpose: that block needs
# the pytest-env plugin, which is not in requirements-dev.txt, so pytest ignores
# it (it warns "Unknown config option: env"). Seeding here is what actually
# takes effect. Settings() rejects a postgres backend without DB credentials, so
# any test that imports the app in the default server profile needs these two.
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_testing_only_min_32_chars")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("MAIN_DB_USER", "test_user")
os.environ.setdefault("MAIN_DB_PASSWORD", "test_password")
# Without this the HTTPS-redirect middleware 301s every plain-http test request.
# httpx follows the redirect and downgrades POST to GET, which then misses the
# POST-only route and lands on the SPA catch-all — a 200 of index.html instead
# of the JSON the test asserted on.
os.environ.setdefault("ENFORCE_HTTPS", "false")
# Tests that run the app lifespan must not try to create databases.
os.environ.setdefault("DB_AUTO_BOOTSTRAP", "false")
os.environ.setdefault("UPDATE_CHECK_ENABLED", "false")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    # base_url=http://localhost so TrustedHostMiddleware accepts the Host header
    return TestClient(app, base_url="http://localhost")


@pytest.fixture(autouse=True)
def reset_auth_rate_limiter(monkeypatch):
    """Give every test a limiter with an empty, in-memory-only counter.

    `rate_limiter.reset()` clears the in-memory cache and NOTHING else. When a
    Postgres is reachable (CI provisions one as a service container) the limiter
    prefers its durable `rate_limit_counters` path, which `reset()` cannot touch
    — so a module firing more than 5 requests per client_id inside one 60s window
    passes locally and 429s in CI.

    Forcing `_check_via_db` to report "unavailable" pins the limiter to the
    in-memory path that `reset()` actually controls, so the suite behaves the
    same whether or not a database happens to be up. Tests that want the durable
    path monkeypatch it back themselves (their patch is applied after this one
    and undone before it).
    """
    from app.middleware.rate_limiter import RateLimiter, rate_limiter

    monkeypatch.setattr(RateLimiter, "_check_via_db", lambda self, client_id, now: None)
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
