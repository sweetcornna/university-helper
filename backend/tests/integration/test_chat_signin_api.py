"""Group-chat API contracts without sending real platform requests."""

from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from app.api.v1 import chaoxing as chaoxing_api
from app.core.security import create_access_token
from app.dependencies import get_current_user_id
from app.main import app
from app.services.course.chaoxing.signin import SigninSessionExpiredError


@pytest.fixture
def chat_client():
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user_id] = lambda: "7"
    token = create_access_token({"user_id": 7, "tenant_db_name": "tenant_chatapi"})
    try:
        yield TestClient(app, base_url="http://localhost", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_chat_discovery_preserves_scope_and_warnings(chat_client, monkeypatch):
    task = {"chatId": "123", "activeId": "456", "type": "normal", "subjectType": "chat"}
    get_tasks = Mock(return_value={"tasks": [task], "warnings": ["Latest messages only"], "scope": "latest_messages"})
    monkeypatch.setattr(chaoxing_api.signin_manager, "get_chat_tasks", get_tasks)

    response = chat_client.get("/api/v1/chaoxing/chat-activities?chat_id=123")

    assert response.status_code == 200
    assert response.json()["data"] == [task]
    assert response.json()["warnings"] == ["Latest messages only"]
    assert response.json()["scope"] == "latest_messages"
    get_tasks.assert_called_once_with(user_id="7", chat_id="123")


@pytest.mark.parametrize("chat_id", ["invalid", "0", "1/2", "1\n2", "1" * 33])
def test_invalid_discovery_target_is_rejected_before_service_call(chat_client, monkeypatch, chat_id):
    get_tasks = Mock()
    monkeypatch.setattr(chaoxing_api.signin_manager, "get_chat_tasks", get_tasks)

    response = chat_client.get("/api/v1/chaoxing/chat-activities", params={"chat_id": chat_id})

    assert response.status_code == 422
    get_tasks.assert_not_called()


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (
            {"chat_id": "123", "active_id": "456"},
            {
                "chat_id": "123",
                "active_id": "456",
                "activity_url": None,
                "latitude": None,
                "longitude": None,
                "address": None,
            },
        ),
        (
            {
                "activity_url": "https://mobilelearn.chaoxing.com/sign/preStuSign?chatId=123&activeId=456",
                "latitude": 39.9087,
                "longitude": 116.3975,
                "address": "天安门",
            },
            {
                "chat_id": None,
                "active_id": None,
                "activity_url": "https://mobilelearn.chaoxing.com/sign/preStuSign?chatId=123&activeId=456",
                "latitude": 39.9087,
                "longitude": 116.3975,
                "address": "天安门",
            },
        ),
    ],
)
def test_chat_sign_forwards_only_group_target(chat_client, monkeypatch, target, expected):
    sign = Mock(return_value={"status": True, "message": "success", "data": {"task": {"subjectType": "chat"}}})
    monkeypatch.setattr(chaoxing_api.signin_manager, "sign_chat_once", sign)

    response = chat_client.post(
        "/api/v1/chaoxing/chat-sign", json={"username": "test", "password": "test-only", **target}
    )

    assert response.status_code == 200
    assert response.json()["status"] is True
    assert response.json()["data"]["task"]["subjectType"] == "chat"
    sign.assert_called_once_with(user_id="7", username="test", password="test-only", **expected)


def test_chat_sign_invalid_target_returns_validation_error(chat_client, monkeypatch):
    monkeypatch.setattr(
        chaoxing_api.signin_manager, "sign_chat_once", Mock(side_effect=ValueError("chat_id is required"))
    )

    response = chat_client.post("/api/v1/chaoxing/chat-sign", json={"username": "test", "password": "test-only"})

    assert response.status_code == 422
    assert response.json()["detail"] == "chat_id is required"


def test_unsupported_chat_sign_is_a_visible_business_failure(chat_client, monkeypatch):
    monkeypatch.setattr(
        chaoxing_api.signin_manager,
        "sign_chat_once",
        Mock(return_value={"status": False, "message": "仅支持普通群聊签到", "data": {}}),
    )

    response = chat_client.post(
        "/api/v1/chaoxing/chat-sign",
        json={"username": "test", "password": "test-only", "chat_id": "123", "active_id": "456"},
    )

    assert response.status_code == 200
    assert response.json()["status"] is False
    assert "普通" in response.json()["message"]


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    ("error", "http_status"),
    [(SigninSessionExpiredError("expired"), 401), (requests.RequestException("sensitive token"), 502)],
)
def test_chat_errors_keep_platform_status_without_leaking_credentials(
    chat_client, monkeypatch, method, error, http_status
):
    endpoint = "get_chat_tasks" if method == "get" else "sign_chat_once"
    monkeypatch.setattr(chaoxing_api.signin_manager, endpoint, Mock(side_effect=error))

    if method == "get":
        response = chat_client.get("/api/v1/chaoxing/chat-activities")
    else:
        response = chat_client.post(
            "/api/v1/chaoxing/chat-sign",
            json={"username": "test", "password": "test-only", "chat_id": "123", "active_id": "456"},
        )

    assert response.status_code == http_status
    assert "sensitive" not in response.text
