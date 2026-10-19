"""HTTP errors must distinguish an unavailable platform from an empty activity list."""

from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.v1 import chaoxing as chaoxing_api
from app.dependencies import get_current_user, get_current_user_id
from app.main import app
from app.services.course.chaoxing.signin import SigninSessionExpiredError


@pytest.fixture
def authenticated_client():
    from app.core.security import create_access_token

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user_id] = lambda: "7"
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    token = create_access_token({"user_id": 7, "tenant_db_name": "tenant_signintest"})
    try:
        yield TestClient(app, base_url="http://localhost", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/chaoxing/tasks", "get_active_tasks"),
        ("/api/v1/chaoxing/courses", "get_courses"),
        ("/api/v1/chaoxing/classes", "get_classes"),
        ("/api/v1/chaoxing/classes/123/activities", "get_class_activities"),
        ("/api/v1/course/courses", "get_courses"),
    ],
)
def test_expired_platform_login_is_not_a_successful_empty_list(authenticated_client, monkeypatch, path, method):
    monkeypatch.setattr(chaoxing_api.signin_manager, method, Mock(side_effect=SigninSessionExpiredError("expired")))

    response = authenticated_client.get(path)

    assert response.status_code == 401
    assert "学习通" in response.json()["detail"]
    assert "平台账号" in response.json()["detail"]
    assert "data" not in response.json()


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/chaoxing/tasks", "get_active_tasks"),
        ("/api/v1/chaoxing/courses", "get_courses"),
        ("/api/v1/chaoxing/classes/123/activities", "get_class_activities"),
        ("/api/v1/course/courses", "get_courses"),
    ],
)
def test_upstream_detection_error_is_retryable_without_leaking_response(
    authenticated_client, monkeypatch, path, method
):
    monkeypatch.setattr(
        chaoxing_api.signin_manager,
        method,
        Mock(side_effect=requests.RequestException("upstream token=sensitive")),
    )

    response = authenticated_client.get(path)

    assert response.status_code == 502
    assert "重" in response.json()["detail"]
    assert "sensitive" not in response.text
    assert "data" not in response.json()


def test_successful_detection_can_still_report_no_active_signins(authenticated_client, monkeypatch):
    monkeypatch.setattr(chaoxing_api.signin_manager, "get_active_tasks", Mock(return_value=[]))

    response = authenticated_client.get("/api/v1/chaoxing/tasks")

    assert response.status_code == 200
    assert response.json()["status"] is True
    assert response.json()["data"] == []
