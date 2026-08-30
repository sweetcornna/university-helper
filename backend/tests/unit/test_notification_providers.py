"""Tests for notification provider SSRF guarding (F55) and public interface stability."""

import inspect
import socket
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.notification.providers import (
    Bark,
    DefaultNotification,
    NotificationFactory,
    NotificationService,
    Qmsg,
    ServerChan,
    Telegram,
    validate_notification_url,
)

_PUBLIC_NOTIFICATION_HOSTS = {
    "api.day.app",
    "sctapi.ftqq.com",
    "qmsg.zendee.cn",
    "api.telegram.org",
}

_SENSITIVE_WEBHOOK_URL = (
    "https://notify-user:NOTIFICATION_SENTINEL@api.day.app/webhook/NOTIFICATION_SENTINEL?token=NOTIFICATION_SENTINEL"
)
_NOTIFICATION_SENTINEL = "NOTIFICATION_SENTINEL"


@pytest.fixture
def public_notification_dns(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in _PUBLIC_NOTIFICATION_HOSTS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        raise socket.gaierror(f"unexpected DNS lookup in unit test: {host}")

    monkeypatch.setattr("app.services.notification.providers.socket.getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/send",
        "http://localhost/send",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/x",  # private
        "http://192.168.1.10/x",  # private
        "http://172.16.0.1/x",  # private
        "http://[::1]/x",  # ipv6 loopback
        "ftp://example.com/x",  # bad scheme
        "file:///etc/passwd",  # bad scheme
        "javascript:alert(1)",  # bad scheme
        "https://metadata.google.internal/x",  # link-local alias
        "not-a-url",
    ],
)
def test_validate_rejects_internal_or_bad_urls(url):
    assert validate_notification_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://api.day.app/token",
        "https://sctapi.ftqq.com/SCT.send",
        "http://qmsg.zendee.cn/send/key",
        "https://api.telegram.org/bot123/sendMessage",
    ],
)
def test_validate_accepts_public_https_urls(public_notification_dns, url):
    assert validate_notification_url(url) is True


def _build(provider_cls, url):
    svc = provider_cls()
    svc.config_set({"url": url, "tg_chat_id": "123"})
    svc.init_notification()
    return svc


def _log_text(logger_mock):
    return "\n".join(str(call.args[0]) for call in logger_mock.mock_calls if call.args)


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_providers_do_not_post_to_internal_url(provider_cls):
    """A configured internal URL must never reach requests.post."""
    svc = _build(provider_cls, "http://169.254.169.254/latest/meta-data/")
    with patch("app.services.notification.providers.requests.post") as mock_post:
        svc.send("hello")
    assert not mock_post.called, f"{provider_cls.__name__} POSTed to a blocked URL"


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_providers_post_to_public_url(public_notification_dns, provider_cls):
    """A valid public URL must still be delivered (interface unchanged)."""
    svc = _build(provider_cls, "https://api.day.app/token")
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True}
    with patch("app.services.notification.providers.requests.post", return_value=response) as mock_post:
        assert svc.send("hello") is True
    assert mock_post.called, f"{provider_cls.__name__} did not deliver to a public URL"
    assert mock_post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_providers_reject_redirect_without_following(public_notification_dns, provider_cls):
    """A public webhook redirect must fail without a second request."""
    svc = _build(provider_cls, "https://api.day.app/token")
    response = MagicMock()
    response.status_code = 302
    response.headers = {"Location": "http://127.0.0.1/latest/meta-data/"}

    with patch("app.services.notification.providers.requests.post", return_value=response) as mock_post:
        assert svc.send("hello") is False

    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["allow_redirects"] is False
    response.json.assert_not_called()


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_provider_init_logs_do_not_include_webhook_credentials(provider_cls):
    svc = provider_cls()
    svc.config_set({"url": _SENSITIVE_WEBHOOK_URL, "tg_chat_id": _NOTIFICATION_SENTINEL})

    with patch("app.services.notification.providers.logger") as mock_logger:
        svc.init_notification()

    logs = _log_text(mock_logger)
    assert svc.name in logs
    assert _NOTIFICATION_SENTINEL not in logs
    assert "?token=" not in logs
    assert "notify-user:" not in logs


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_validation_failure_log_does_not_include_webhook_credentials(provider_cls):
    svc = _build(provider_cls, _SENSITIVE_WEBHOOK_URL)

    with (
        patch("app.services.notification.providers.validate_notification_url", return_value=False),
        patch("app.services.notification.providers.logger") as mock_logger,
    ):
        assert svc.send("hello") is False

    logs = _log_text(mock_logger)
    assert svc.name in logs
    assert "校验失败" in logs
    assert _NOTIFICATION_SENTINEL not in logs
    assert "?token=" not in logs
    assert "notify-user:" not in logs


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
@pytest.mark.parametrize("exception_cls", [requests.exceptions.HTTPError, requests.exceptions.Timeout])
def test_request_error_logs_do_not_include_webhook_credentials(provider_cls, exception_cls):
    svc = _build(provider_cls, _SENSITIVE_WEBHOOK_URL)
    request_error = exception_cls(f"request failed for {_SENSITIVE_WEBHOOK_URL}")

    with (
        patch.object(svc, "_url_allowed", return_value=True),
        patch("app.services.notification.providers.requests.post", side_effect=request_error),
        patch("app.services.notification.providers.logger") as mock_logger,
    ):
        assert svc.send("hello") is False

    logs = _log_text(mock_logger)
    assert svc.name in logs
    assert exception_cls.__name__ in logs
    assert _NOTIFICATION_SENTINEL not in logs
    assert "?token=" not in logs
    assert "notify-user:" not in logs


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_success_log_does_not_include_webhook_credentials(public_notification_dns, provider_cls):
    svc = _build(provider_cls, _SENSITIVE_WEBHOOK_URL)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True, "webhook": _SENSITIVE_WEBHOOK_URL}

    with (
        patch("app.services.notification.providers.requests.post", return_value=response),
        patch("app.services.notification.providers.logger") as mock_logger,
    ):
        assert svc.send("hello") is True

    logs = _log_text(mock_logger)
    assert svc.name in logs
    assert _NOTIFICATION_SENTINEL not in logs
    assert "?token=" not in logs
    assert "notify-user:" not in logs


def test_public_interface_is_stable():
    """G:learning may import these names; keep them present."""
    assert hasattr(NotificationFactory, "create_service")
    assert issubclass(ServerChan, NotificationService)
    # send(message) signature stays a single positional message arg.
    svc = ServerChan()
    params = list(inspect.signature(svc.send).parameters)
    assert params == ["message"]


@pytest.mark.parametrize("provider_name", ["logger", "requests"])
def test_factory_disables_non_provider_globals(provider_name):
    service = NotificationFactory.create_service({"provider": provider_name, "url": "https://example.invalid/notify"})

    assert isinstance(service, DefaultNotification)
    assert service.disabled is True


def test_factory_disables_unknown_provider():
    service = NotificationFactory.create_service({"provider": "NotAProvider", "url": "https://example.invalid/notify"})

    assert isinstance(service, DefaultNotification)
    assert service.disabled is True


@pytest.mark.parametrize(
    ("provider_name", "provider_cls", "extra_config"),
    [
        ("ServerChan", ServerChan, {}),
        ("Qmsg", Qmsg, {}),
        ("Bark", Bark, {}),
        ("Telegram", Telegram, {"tg_chat_id": "123"}),
    ],
)
def test_factory_builds_supported_providers(provider_name, provider_cls, extra_config):
    config = {"provider": provider_name, "url": "https://example.invalid/notify", **extra_config}

    service = NotificationFactory.create_service(config)

    assert isinstance(service, provider_cls)
    assert service.disabled is False
