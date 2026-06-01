"""Tests for notification provider SSRF guarding (F55) and public interface stability."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.notification.providers import (
    Bark,
    NotificationFactory,
    NotificationService,
    Qmsg,
    ServerChan,
    Telegram,
    validate_notification_url,
)


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
def test_validate_accepts_public_https_urls(url):
    assert validate_notification_url(url) is True


def _build(provider_cls, url):
    svc = provider_cls()
    svc.config_set({"url": url, "tg_chat_id": "123"})
    svc.init_notification()
    return svc


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_providers_do_not_post_to_internal_url(provider_cls):
    """A configured internal URL must never reach requests.post."""
    svc = _build(provider_cls, "http://169.254.169.254/latest/meta-data/")
    with patch("app.services.notification.providers.requests.post") as mock_post:
        svc.send("hello")
    assert not mock_post.called, f"{provider_cls.__name__} POSTed to a blocked URL"


@pytest.mark.parametrize("provider_cls", [ServerChan, Qmsg, Bark, Telegram])
def test_providers_post_to_public_url(provider_cls):
    """A valid public URL must still be delivered (interface unchanged)."""
    svc = _build(provider_cls, "https://api.day.app/token")
    response = MagicMock()
    response.json.return_value = {"ok": True}
    with patch(
        "app.services.notification.providers.requests.post", return_value=response
    ) as mock_post:
        svc.send("hello")
    assert mock_post.called, f"{provider_cls.__name__} did not deliver to a public URL"


def test_public_interface_is_stable():
    """G:learning may import these names; keep them present."""
    assert hasattr(NotificationFactory, "create_service")
    assert issubclass(ServerChan, NotificationService)
    # send(message) signature stays a single positional message arg.
    svc = ServerChan()
    import inspect

    params = list(inspect.signature(svc.send).parameters)
    assert params == ["message"]
