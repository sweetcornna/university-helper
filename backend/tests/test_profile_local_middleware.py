from fastapi.testclient import TestClient

from tests.conftest import build_app

PROTECTED = "/api/v1/course/tasks"  # course.py route, behind get_current_user


def test_server_profile_gate_rejects_missing_token():
    # Server mode: tenant_isolation_middleware IS registered → its 401 fires
    # before any route/dependency runs.
    with build_app("server") as app:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(PROTECTED)  # no Authorization header
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing token"  # pins it to the gate


def test_local_profile_gate_not_registered():
    # Local mode: the gate is SKIPPED. With the gate gone, a missing token is no
    # longer a 401 from the gate. Because the gate is OUTERMOST it would 401
    # regardless of dependency_overrides, so a non-401 here proves it is unregistered.
    with build_app("local") as app:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(PROTECTED)  # no Authorization header
    assert resp.status_code != 401
