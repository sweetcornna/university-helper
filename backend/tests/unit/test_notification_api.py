"""Security-focused HTTP tests for the notification test endpoint."""

import logging
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.course as course_api
from app.dependencies import get_current_user

_NOTIFICATION_SENTINEL = "NOTIFICATION_SENTINEL"
_SENTINEL_URL = "https://notify.example/NOTIFICATION_SENTINEL?token=NOTIFICATION_SENTINEL"


@pytest.fixture
def notify_client():
    app = FastAPI()
    app.include_router(course_api.router, prefix="/api/v1/course")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1}
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("service", ["ServerChan", "Qmsg", "Bark", "Telegram"])
def test_notify_route_accepts_only_canonical_providers(
    notify_client,
    monkeypatch,
    service,
):
    provider = Mock(disabled=False)
    provider.send.return_value = True
    factory = Mock(return_value=provider)
    monkeypatch.setattr(course_api, "validate_notification_url", lambda _url: True)
    monkeypatch.setattr(course_api.NotificationFactory, "create_service", factory)

    response = notify_client.post(
        "/api/v1/course/notify/test",
        json={"service": service, "url": "https://notify.example/send"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Test notification sent"}
    assert factory.call_args.args[0]["provider"] == service
    provider.send.assert_called_once()


def test_notify_route_rejects_unknown_provider_without_leaking_input(
    notify_client,
    monkeypatch,
    caplog,
):
    validator = Mock(return_value=True)
    factory = Mock()
    monkeypatch.setattr(course_api, "validate_notification_url", validator)
    monkeypatch.setattr(course_api.NotificationFactory, "create_service", factory)

    with caplog.at_level(logging.WARNING, logger=course_api.__name__):
        response = notify_client.post(
            "/api/v1/course/notify/test",
            json={
                "service": f"Unknown-{_NOTIFICATION_SENTINEL}",
                "url": _SENTINEL_URL,
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported notification service"}
    assert _NOTIFICATION_SENTINEL not in response.text
    assert _NOTIFICATION_SENTINEL not in caplog.text
    validator.assert_not_called()
    factory.assert_not_called()


def test_notify_route_validator_failure_is_fail_closed_and_redacted(
    notify_client,
    monkeypatch,
    caplog,
):
    factory = Mock()
    monkeypatch.setattr(
        course_api,
        "validate_notification_url",
        Mock(side_effect=RuntimeError(_SENTINEL_URL)),
    )
    monkeypatch.setattr(course_api.NotificationFactory, "create_service", factory)

    with caplog.at_level(logging.WARNING, logger=course_api.__name__):
        response = notify_client.post(
            "/api/v1/course/notify/test",
            json={"service": "Bark", "url": _SENTINEL_URL},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Notification URL must be a public http(s) address"}
    assert _NOTIFICATION_SENTINEL not in response.text
    assert _NOTIFICATION_SENTINEL not in caplog.text
    factory.assert_not_called()


def test_notify_route_delivery_failure_has_fixed_response_and_log(
    notify_client,
    monkeypatch,
    caplog,
):
    provider = Mock(disabled=False)
    provider.send.side_effect = RuntimeError(_SENTINEL_URL)
    monkeypatch.setattr(course_api, "validate_notification_url", lambda _url: True)
    monkeypatch.setattr(
        course_api.NotificationFactory,
        "create_service",
        Mock(return_value=provider),
    )

    with caplog.at_level(logging.WARNING, logger=course_api.__name__):
        response = notify_client.post(
            "/api/v1/course/notify/test",
            json={"service": "Bark", "url": _SENTINEL_URL},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "Failed to send test notification"}
    assert _NOTIFICATION_SENTINEL not in response.text
    assert _NOTIFICATION_SENTINEL not in caplog.text
