"""Failure-contract tests for the Adapter and Yanxi answer providers."""

from unittest.mock import patch

import pytest
import requests

from app.services.course.chaoxing.answer_base import Tiku, TikuFallback
from app.services.course.chaoxing.answer_providers import TikuAdapter, TikuYanxi

_TOKEN_SENTINEL = "TIKU_PROVIDER_TOKEN_SENTINEL"
_RESPONSE_SENTINEL = "TIKU_PROVIDER_RESPONSE_SENTINEL"
_QUESTION = {"title": "中国的首都是哪里？", "type": "single", "options": "A.北京\nB.上海"}


class _Response:
    def __init__(self, payload=None, status_code=200, text=_RESPONSE_SENTINEL):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


def _logs(mock_logger):
    return "\n".join(str(call.args[0]) for call in mock_logger.mock_calls if call.args)


def _adapter():
    provider = TikuAdapter()
    provider.api = f"https://adapter.example.invalid/query?token={_TOKEN_SENTINEL}"
    return provider


def _yanxi():
    provider = TikuYanxi()
    provider.api = f"https://yanxi.example.invalid/query?token={_TOKEN_SENTINEL}"
    provider._token = _TOKEN_SENTINEL
    return provider


@pytest.mark.parametrize(
    ("provider_factory", "request_path"),
    [
        (_adapter, "app.services.course.chaoxing.answer_providers.adapter.requests.post"),
        (_yanxi, "app.services.course.chaoxing.answer_providers.yanxi.requests.get"),
    ],
)
@pytest.mark.parametrize(
    "request_error",
    [
        requests.exceptions.ConnectionError("connection failed"),
        requests.exceptions.Timeout("request timed out"),
        requests.exceptions.RequestException("request failed"),
    ],
)
def test_network_failures_return_none_without_logging_error_details(provider_factory, request_path, request_error):
    provider = provider_factory()

    with (
        patch(request_path, side_effect=request_error),
        patch(f"{request_path.rsplit('.', 2)[0]}.logger") as mock_logger,
    ):
        assert provider._query(_QUESTION) is None

    logs = _logs(mock_logger)
    assert provider.name in logs
    assert _TOKEN_SENTINEL not in logs
    assert _RESPONSE_SENTINEL not in logs
    assert str(request_error) not in logs


@pytest.mark.parametrize(
    ("provider_factory", "request_path"),
    [
        (_adapter, "app.services.course.chaoxing.answer_providers.adapter.requests.post"),
        (_yanxi, "app.services.course.chaoxing.answer_providers.yanxi.requests.get"),
    ],
)
def test_invalid_json_returns_none_without_logging_response(provider_factory, request_path):
    provider = provider_factory()
    invalid_json = ValueError(f"invalid response: {_RESPONSE_SENTINEL}")

    with (
        patch(request_path, return_value=_Response(invalid_json)),
        patch(f"{request_path.rsplit('.', 2)[0]}.logger") as mock_logger,
    ):
        assert provider._query(_QUESTION) is None

    logs = _logs(mock_logger)
    assert provider.name in logs
    assert _TOKEN_SENTINEL not in logs
    assert _RESPONSE_SENTINEL not in logs


@pytest.mark.parametrize(
    ("provider_factory", "request_path"),
    [
        (_adapter, "app.services.course.chaoxing.answer_providers.adapter.requests.post"),
        (_yanxi, "app.services.course.chaoxing.answer_providers.yanxi.requests.get"),
    ],
)
def test_http_failure_returns_none_without_logging_response(provider_factory, request_path):
    provider = provider_factory()

    with (
        patch(request_path, return_value=_Response(status_code=503)),
        patch(f"{request_path.rsplit('.', 2)[0]}.logger") as mock_logger,
    ):
        assert provider._query(_QUESTION) is None

    logs = _logs(mock_logger)
    assert provider.name in logs
    assert "503" in logs
    assert _TOKEN_SENTINEL not in logs
    assert _RESPONSE_SENTINEL not in logs


def test_adapter_success_preserves_answer_format():
    provider = _adapter()
    response = _Response({"answer": {"bestAnswer": ["北京", "Beijing"]}})

    with patch("app.services.course.chaoxing.answer_providers.adapter.requests.post", return_value=response):
        assert provider._query(_QUESTION) == "北京\nBeijing"


def test_yanxi_success_preserves_answer_and_updates_remaining_times():
    provider = _yanxi()
    response = _Response({"code": 1, "data": {"answer": " 北京 ", "times": 97}})

    with patch("app.services.course.chaoxing.answer_providers.yanxi.requests.get", return_value=response):
        assert provider._query(_QUESTION) == "北京"

    assert provider._times == 97


@pytest.mark.parametrize(
    ("provider_factory", "request_path", "payload"),
    [
        (_adapter, "app.services.course.chaoxing.answer_providers.adapter.requests.post", {}),
        (_yanxi, "app.services.course.chaoxing.answer_providers.yanxi.requests.get", {"code": 1, "data": {}}),
    ],
)
def test_missing_response_fields_are_provider_misses_without_response_logging(provider_factory, request_path, payload):
    provider = provider_factory()

    with (
        patch(request_path, return_value=_Response(payload)),
        patch(f"{request_path.rsplit('.', 2)[0]}.logger") as mock_logger,
    ):
        assert provider._query(_QUESTION) is None

    logs = _logs(mock_logger)
    assert provider.name in logs
    assert _TOKEN_SENTINEL not in logs
    assert _RESPONSE_SENTINEL not in logs


class _FallbackHit(Tiku):
    def __init__(self):
        super().__init__()
        self.name = "fallback-hit"

    def _query(self, q_info):
        return "A"


@pytest.mark.parametrize(
    ("provider_factory", "request_path"),
    [
        (_adapter, "app.services.course.chaoxing.answer_providers.adapter.requests.post"),
        (_yanxi, "app.services.course.chaoxing.answer_providers.yanxi.requests.get"),
    ],
)
def test_external_failure_allows_fallback_to_next_provider(provider_factory, request_path):
    provider = provider_factory()
    fallback = TikuFallback([provider, _FallbackHit()])
    fallback.DISABLE = False

    with patch(request_path, side_effect=requests.exceptions.ConnectionError("offline")):
        assert fallback._query(_QUESTION) == "A"
