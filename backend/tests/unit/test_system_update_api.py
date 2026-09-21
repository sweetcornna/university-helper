"""GET /api/v1/system/update: administrators only, server edition only."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from tests.conftest import build_app


def _db_returning(*rows):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.side_effect = list(rows)
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cur


def _auth(user_id=5):
    token = create_access_token({"user_id": user_id, "tenant_db_name": "tenant_x"})
    return {"Authorization": f"Bearer {token}"}


class _FakeChecker:
    async def get_status(self):
        return {"enabled": True, "current": "1.4.7", "latest": "1.4.8", "has_update": True}


@pytest.fixture
def server_client():
    with build_app("server", ENFORCE_HTTPS="false", ADMIN_EMAILS="") as app:
        app.state.update_checker = _FakeChecker()
        yield TestClient(app, base_url="http://localhost")


def test_requires_login(server_client):
    assert server_client.get("/api/v1/system/update").status_code == 401


def test_non_admin_gets_403(server_client):
    conn, _ = _db_returning({"id": 1})
    with patch("app.services.admin.get_db_session", return_value=conn):
        resp = server_client.get("/api/v1/system/update", headers=_auth(user_id=5))
    assert resp.status_code == 403


def test_first_registered_user_is_admin_when_no_emails_configured(server_client):
    conn, cur = _db_returning({"id": 5})
    with patch("app.services.admin.get_db_session", return_value=conn):
        resp = server_client.get("/api/v1/system/update", headers=_auth(user_id=5))
    assert resp.status_code == 200
    assert resp.json()["latest"] == "1.4.8"
    assert "MIN(id)" in cur.execute.call_args.args[0]


def test_admin_emails_take_precedence_over_first_user(monkeypatch):
    with build_app("server", ENFORCE_HTTPS="false", ADMIN_EMAILS="Ops@Example.com, boss@example.com") as app:
        app.state.update_checker = _FakeChecker()
        client = TestClient(app, base_url="http://localhost")
        admin_conn, admin_cur = _db_returning({"email": "ops@example.com"})
        with patch("app.services.admin.get_db_session", return_value=admin_conn):
            allowed = client.get("/api/v1/system/update", headers=_auth(user_id=9))
        other_conn, _ = _db_returning({"email": "first@example.com"})
        with patch("app.services.admin.get_db_session", return_value=other_conn):
            denied = client.get("/api/v1/system/update", headers=_auth(user_id=1))

    assert allowed.status_code == 200
    assert "SELECT email FROM users" in admin_cur.execute.call_args.args[0]
    assert denied.status_code == 403


def test_disabled_checker_reports_current_version(server_client):
    server_client.app.state.update_checker = None
    conn, _ = _db_returning({"id": 5})
    with patch("app.services.admin.get_db_session", return_value=conn):
        resp = server_client.get("/api/v1/system/update", headers=_auth(user_id=5))
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "current": server_client.app.version, "has_update": False}


def test_route_is_not_mounted_in_desktop_build():
    with build_app("local", ENFORCE_HTTPS="false", CORS_ORIGINS='["http://127.0.0.1:8000"]') as app:
        paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/system/update" not in paths


def test_app_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    import app.main as main_mod

    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    assert main_mod.app.version == pyproject["project"]["version"]
