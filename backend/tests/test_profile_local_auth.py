"""The desktop build has no user accounts: auth endpoints must fail clearly, not 500."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import build_app

LOCAL_ENV = {"ENFORCE_HTTPS": "false", "CORS_ORIGINS": '["http://127.0.0.1:8000"]'}


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/auth/register", {"username": "alice", "email": "alice@example.com", "password": "Password1"}),
        ("/api/v1/auth/login", {"email": "alice@example.com", "password": "Password1"}),
        ("/api/v1/auth/register", {"username": "!", "email": "not-an-email"}),
    ],
)
def test_local_profile_auth_returns_409_with_guidance(path, body):
    with build_app("local", **LOCAL_ENV) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
        resp = client.post(path, json=body)

    assert resp.status_code == 409
    assert resp.json()["code"] == "LocalProfileAuthUnavailable"
    assert "桌面版" in resp.json()["message"]


def test_server_profile_register_is_not_blocked_by_local_guard():
    with build_app("server", ENFORCE_HTTPS="false") as app:
        client = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
        resp = client.post("/api/v1/auth/register", json={"username": "!", "email": "bad"})

    assert resp.status_code == 422
