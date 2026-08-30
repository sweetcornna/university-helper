"""Regression tests for answer-provider endpoint SSRF boundaries."""

from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

import app.api.v1.course as course_api
from app.services.course.chaoxing.answer_providers import AI, SiliconFlow, TikuAdapter
from app.services.course.chaoxing.endpoint_security import (
    INVALID_ENDPOINT_CONFIG_DETAIL,
    UnsafeEndpointError,
    assert_public_endpoint,
    is_public_endpoint,
    validate_tiku_config,
)
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager

PUBLIC_ENDPOINT = "https://93.184.216.34/v1/chat/completions"
QUESTION = {"type": "single", "title": "首都是哪里？", "options": "A.北京\nB.上海"}


class _Response:
    def __init__(self, payload=None, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.headers = headers or {}

    def json(self):
        return self.payload


def _build_ai(endpoint=PUBLIC_ENDPOINT, http_proxy=None):
    provider = AI()
    provider.endpoint = endpoint
    provider.key = "key"
    provider.model = "model"
    provider.http_proxy = http_proxy
    provider._httpx_client = Mock()
    return provider


def _build_siliconflow(endpoint=PUBLIC_ENDPOINT, http_proxy=None):
    provider = SiliconFlow()
    provider.api_endpoint = endpoint
    provider.api_key = "key"
    provider.model_name = "model"
    provider.http_proxy = http_proxy
    provider._session = Mock()
    provider.min_interval = 0
    provider.max_retries = 1
    return provider


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/query",
        "http://localhost/query",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/query",
        "http://[::ffff:8.8.8.8]/query",
        "http://10.0.0.1/query",
        "http://[fc00::1]/query",
    ],
)
def test_private_and_metadata_endpoints_are_rejected(url):
    assert not is_public_endpoint(url)


def test_dns_resolving_to_private_address_is_rejected(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "private.example"
        return [(2, 1, 6, "", ("192.168.10.4", 0))]

    monkeypatch.setattr(
        "app.services.course.chaoxing.endpoint_security.socket.getaddrinfo",
        fake_getaddrinfo,
    )
    assert not is_public_endpoint("https://private.example/query")


def test_any_non_public_address_in_multi_address_dns_answer_is_rejected(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "mixed.example"
        return [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("10.0.0.4", 0)),
        ]

    monkeypatch.setattr(
        "app.services.course.chaoxing.endpoint_security.socket.getaddrinfo",
        fake_getaddrinfo,
    )
    assert not is_public_endpoint("https://mixed.example/query")


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_public_http_and_https_endpoint_are_allowed_without_network_lookup(scheme):
    assert is_public_endpoint(f"{scheme}://93.184.216.34/v1/chat/completions")


def test_public_hostname_is_allowed_when_all_dns_addresses_are_global(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "public.example"
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(
        "app.services.course.chaoxing.endpoint_security.socket.getaddrinfo",
        fake_getaddrinfo,
    )
    assert is_public_endpoint("https://public.example/query")


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@93.184.216.34/query",
        "http://@93.184.216.34/query",
        r"http://127.0.0.1:8080\@8.8.8.8/query",
    ],
)
def test_userinfo_and_backslash_authority_smuggling_are_rejected(url):
    assert not is_public_endpoint(url)


@pytest.mark.parametrize("failure", [UnicodeError("dns secret"), RuntimeError("resolver secret")])
def test_all_dns_resolution_errors_fail_closed_without_details(monkeypatch, failure):
    def fake_getaddrinfo(*args, **kwargs):
        raise failure

    monkeypatch.setattr(
        "app.services.course.chaoxing.endpoint_security.socket.getaddrinfo",
        fake_getaddrinfo,
    )

    endpoint = "https://resolver.example/query"
    assert not is_public_endpoint(endpoint)
    with pytest.raises(UnsafeEndpointError) as exc_info:
        assert_public_endpoint(endpoint)
    assert str(exc_info.value) == INVALID_ENDPOINT_CONFIG_DETAIL
    assert "secret" not in str(exc_info.value)


def test_private_proxy_is_rejected_before_provider_initialization():
    config = {
        "provider": "AI",
        "endpoint": PUBLIC_ENDPOINT,
        "key": "key",
        "model": "model",
        "http_proxy": "http://127.0.0.1:8080",
    }

    with pytest.raises(UnsafeEndpointError):
        validate_tiku_config(config)


def test_explicitly_blank_siliconflow_endpoint_is_rejected():
    with pytest.raises(UnsafeEndpointError):
        validate_tiku_config({"provider": "SiliconFlow", "siliconflow_endpoint": ""})


@pytest.mark.parametrize(
    ("provider_cls", "config"),
    [
        (TikuAdapter, {"provider": "TikuAdapter", "url": "http://127.0.0.1/query"}),
        (
            AI,
            {
                "provider": "AI",
                "endpoint": "http://127.0.0.1/query",
                "key": "key",
                "model": "model",
            },
        ),
        (
            SiliconFlow,
            {"provider": "SiliconFlow", "siliconflow_endpoint": "http://127.0.0.1/query", "siliconflow_key": "key"},
        ),
    ],
)
def test_provider_initialization_rejects_private_endpoint(provider_cls, config):
    provider = provider_cls()
    provider.config_set(config)
    with pytest.raises(UnsafeEndpointError):
        provider.init_tiku()


@pytest.mark.parametrize(
    ("provider_cls", "config"),
    [
        (
            TikuAdapter,
            {"provider": "TikuAdapter", "url": PUBLIC_ENDPOINT, "http_proxy": "http://127.0.0.1:8080"},
        ),
        (
            AI,
            {
                "provider": "AI",
                "endpoint": PUBLIC_ENDPOINT,
                "key": "key",
                "model": "model",
                "http_proxy": "http://127.0.0.1:8080",
            },
        ),
        (
            SiliconFlow,
            {
                "provider": "SiliconFlow",
                "siliconflow_endpoint": PUBLIC_ENDPOINT,
                "siliconflow_key": "key",
                "http_proxy": "http://127.0.0.1:8080",
            },
        ),
    ],
)
def test_provider_initialization_rejects_private_proxy(provider_cls, config):
    provider = provider_cls()
    provider.config_set(config)
    with pytest.raises(UnsafeEndpointError):
        provider.init_tiku()


@pytest.mark.parametrize("provider_cls", [TikuAdapter, AI, SiliconFlow])
def test_provider_rechecks_endpoint_before_outbound_request(provider_cls):
    if provider_cls is TikuAdapter:
        provider = TikuAdapter()
        provider.api = "http://127.0.0.1/query"
        request_path = "app.services.course.chaoxing.answer_providers.adapter.requests.post"
        with patch(request_path) as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()
    elif provider_cls is AI:
        provider = _build_ai(endpoint="http://127.0.0.1/query")
        with patch.object(provider._httpx_client, "post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()
    else:
        provider = _build_siliconflow(endpoint="http://127.0.0.1/query")
        with patch.object(provider._session, "post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()


@pytest.mark.parametrize(
    "bad_endpoint",
    [
        "http://[::ffff:8.8.8.8]/query",
        "http://user:password@93.184.216.34/query",
        r"http://127.0.0.1:8080\@8.8.8.8/query",
    ],
)
@pytest.mark.parametrize("provider_cls", [TikuAdapter, AI, SiliconFlow])
def test_provider_rechecks_endpoint_syntax_before_outbound_request(provider_cls, bad_endpoint):
    if provider_cls is TikuAdapter:
        provider = TikuAdapter()
        provider.api = bad_endpoint
        with patch("app.services.course.chaoxing.answer_providers.adapter.requests.post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()
    elif provider_cls is AI:
        provider = _build_ai(endpoint=bad_endpoint)
        with patch.object(provider._httpx_client, "post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()
    else:
        provider = _build_siliconflow(endpoint=bad_endpoint)
        with patch.object(provider._session, "post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()


def test_ai_rechecks_private_proxy_before_outbound_request():
    provider = _build_ai(http_proxy="http://127.0.0.1:8080")
    with patch.object(provider._httpx_client, "post") as post:
        assert provider._query(QUESTION) is None
    post.assert_not_called()


@pytest.mark.parametrize("proxy", ["http://127.0.0.1:8080", "http://@93.184.216.34:8080"])
@pytest.mark.parametrize("provider_cls", [TikuAdapter, AI, SiliconFlow])
def test_all_providers_recheck_proxy_before_outbound_request(provider_cls, proxy):
    if provider_cls is TikuAdapter:
        provider = TikuAdapter()
        provider.api = PUBLIC_ENDPOINT
        provider.http_proxy = proxy
        with patch("app.services.course.chaoxing.answer_providers.adapter.requests.post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()
    elif provider_cls is AI:
        provider = _build_ai(http_proxy=proxy)
        with patch.object(provider._httpx_client, "post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()
    else:
        provider = _build_siliconflow(http_proxy=proxy)
        with patch.object(provider._session, "post") as post:
            assert provider._query(QUESTION) is None
        post.assert_not_called()


@pytest.mark.parametrize("provider_cls", [TikuAdapter, AI, SiliconFlow])
def test_provider_does_not_follow_redirects(provider_cls):
    if provider_cls is TikuAdapter:
        provider = TikuAdapter()
        provider.api = PUBLIC_ENDPOINT
        with patch(
            "app.services.course.chaoxing.answer_providers.adapter.requests.post",
            return_value=_Response(
                status_code=302,
                headers={"location": "http://127.0.0.1/latest-meta-data"},
            ),
        ) as post:
            assert provider._query(QUESTION) is None
        assert post.call_args.kwargs["allow_redirects"] is False
    elif provider_cls is AI:
        provider = _build_ai()
        provider.max_retries = 1
        provider._httpx_client.post.return_value = _Response(
            status_code=302,
            headers={"location": "http://127.0.0.1/latest-meta-data"},
        )
        assert provider._query(QUESTION) is None
        provider._httpx_client.post.assert_called_once()
        assert provider._httpx_client.post.call_args.kwargs["follow_redirects"] is False
    else:
        provider = _build_siliconflow()
        provider._session.post.return_value = _Response(
            status_code=302,
            headers={"location": "http://127.0.0.1/latest-meta-data"},
        )
        assert provider._query(QUESTION) is None
        assert provider._session.post.call_args.kwargs["allow_redirects"] is False


def test_ai_client_is_constructed_without_following_redirects():
    provider = AI()
    provider.config_set({"provider": "AI", "endpoint": PUBLIC_ENDPOINT, "key": "key", "model": "model"})
    with patch("app.services.course.chaoxing.answer_providers.ai.httpx.Client") as client:
        provider.init_tiku()
    assert client.call_args.kwargs["follow_redirects"] is False


def test_ai_failure_logs_do_not_include_exception_or_response_details(caplog):
    secret = "https://public.example/?token=ai-secret response-body-secret"
    provider = _build_ai()
    provider.max_retries = 1
    provider.min_interval_seconds = 0
    provider._httpx_client.post.side_effect = RuntimeError(secret)

    with patch("app.services.course.chaoxing.answer_providers.ai.logger") as mocked_logger:
        assert provider._query(QUESTION) is None

    assert secret not in str(mocked_logger.mock_calls)
    assert secret not in caplog.text


def test_ai_http_failure_logs_do_not_include_response_body(caplog):
    secret = "https://public.example/?token=ai-body-secret"
    provider = _build_ai()
    provider.max_retries = 1
    provider.min_interval_seconds = 0
    provider._httpx_client.post.return_value = _Response({"error": secret}, status_code=503)

    with patch("app.services.course.chaoxing.answer_providers.ai.logger") as mocked_logger:
        assert provider._query(QUESTION) is None

    assert secret not in str(mocked_logger.mock_calls)
    assert secret not in caplog.text


def test_siliconflow_failure_logs_do_not_include_exception_or_response_details(caplog):
    secret = "https://public.example/?token=sf-secret response-body-secret"
    provider = _build_siliconflow()
    provider._session.post.side_effect = RuntimeError(secret)

    with patch("app.services.course.chaoxing.answer_providers.siliconflow.logger") as mocked_logger:
        assert provider._query(QUESTION) is None

    assert secret not in str(mocked_logger.mock_calls)
    assert secret not in caplog.text


def test_siliconflow_http_failure_logs_do_not_include_response_body(caplog):
    secret = "https://public.example/?token=sf-body-secret"
    provider = _build_siliconflow()
    provider._session.post.return_value = _Response({"error": secret}, status_code=503)

    with patch("app.services.course.chaoxing.answer_providers.siliconflow.logger") as mocked_logger:
        assert provider._query(QUESTION) is None

    assert secret not in str(mocked_logger.mock_calls)
    assert secret not in caplog.text


@pytest.mark.parametrize("provider_cls", [TikuAdapter, AI, SiliconFlow])
def test_public_endpoint_paths_keep_existing_answer_shape(provider_cls):
    response_payload = (
        {"answer": {"bestAnswer": ["A"]}}
        if provider_cls is TikuAdapter
        else {"choices": [{"message": {"content": '{"Answer": ["A"]}'}}]}
    )
    if provider_cls is TikuAdapter:
        provider = TikuAdapter()
        provider.api = PUBLIC_ENDPOINT
        with patch(
            "app.services.course.chaoxing.answer_providers.adapter.requests.post",
            return_value=_Response(response_payload),
        ):
            assert provider._query(QUESTION) == "A"
    elif provider_cls is AI:
        provider = _build_ai()
        provider._httpx_client.post.return_value = _Response(response_payload)
        assert provider._query(QUESTION) == "A"
    else:
        provider = _build_siliconflow()
        provider._session.post.return_value = _Response(response_payload)
        assert provider._query(QUESTION) == "A"


@pytest.mark.asyncio
async def test_course_start_rejects_private_provider_endpoint_before_manager(monkeypatch):
    calls = []

    class FakeManager:
        def start_task(self, **kwargs):
            calls.append(kwargs)
            return "must-not-start"

    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: FakeManager())
    request = course_api.CourseStartRequest(
        platform="chaoxing",
        username="user",
        password="password",
        tiku_config={"provider": "TikuAdapter", "url": "http://127.0.0.1/query"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_course_learning(request, current_user={"user_id": "u1"})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == INVALID_ENDPOINT_CONFIG_DETAIL
    assert calls == []


@pytest.mark.asyncio
async def test_course_start_rejects_dns_resolution_failure_without_details(monkeypatch):
    secret = "resolver-secret"
    calls = []

    class FakeManager:
        def start_task(self, **kwargs):
            calls.append(kwargs)
            return "must-not-start"

    def fail_getaddrinfo(*args, **kwargs):
        raise UnicodeError(secret)

    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: FakeManager())
    monkeypatch.setattr(
        "app.services.course.chaoxing.endpoint_security.socket.getaddrinfo",
        fail_getaddrinfo,
    )
    request = course_api.CourseStartRequest(
        platform="chaoxing",
        username="user",
        password="password",
        tiku_config={"provider": "AI", "endpoint": "https://resolver.example/query", "key": "key", "model": "model"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_course_learning(request, current_user={"user_id": "u1"})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == INVALID_ENDPOINT_CONFIG_DETAIL
    assert secret not in str(exc_info.value.detail)
    assert calls == []


def test_learning_manager_rejects_private_provider_before_state_or_thread():
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    with patch("app.services.course.chaoxing.learning_manager.threading.Thread") as thread:
        with pytest.raises(UnsafeEndpointError):
            manager.start_task(
                "u1",
                {
                    "username": "user",
                    "password": "password",
                    "tiku_config": {"provider": "TikuAdapter", "url": "http://127.0.0.1/query"},
                },
            )
    thread.assert_not_called()
