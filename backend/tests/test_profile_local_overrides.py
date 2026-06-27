from fastapi.testclient import TestClient

from tests.conftest import build_app


def test_course_endpoint_local_no_token_sees_local_user(monkeypatch):
    # course.py uses get_current_user (HTTPBearer auto_error=True). With the local
    # override, no Authorization header is required and _current_user_id() yields "local".
    captured = {}

    class FakeManager:
        def list_tasks(self, user_id):
            captured["user_id"] = user_id
            return [{"task_id": "t1"}]

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.course as course_mod

        monkeypatch.setattr(course_mod, "_get_learning_manager", lambda: FakeManager())
        client = TestClient(app, base_url="http://127.0.0.1")
        resp = client.get("/api/v1/course/tasks")  # NO Authorization header

    assert resp.status_code != 401
    assert resp.status_code == 200
    assert captured["user_id"] == "local"
    assert resp.json()["data"] == [{"task_id": "t1"}]


def test_chaoxing_endpoint_local_no_token_sees_local_user(monkeypatch):
    # chaoxing.py uses get_current_user_id (HTTPBearer auto_error=False) → a plain str.
    captured = {}

    def fake_get_active_tasks(user_id, sign_type):
        captured["user_id"] = user_id
        return []

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod.signin_manager, "get_active_tasks", fake_get_active_tasks)
        client = TestClient(app, base_url="http://127.0.0.1")
        resp = client.get("/api/v1/chaoxing/tasks")  # NO Authorization header

    assert resp.status_code != 401
    assert resp.status_code == 200
    assert captured["user_id"] == "local"


def test_server_profile_same_endpoints_still_401_without_token():
    with build_app("server") as app:
        client = TestClient(app, base_url="http://localhost")
        course = client.get("/api/v1/course/tasks")
        chaoxing = client.get("/api/v1/chaoxing/tasks")
    assert course.status_code == 401
    assert chaoxing.status_code == 401
