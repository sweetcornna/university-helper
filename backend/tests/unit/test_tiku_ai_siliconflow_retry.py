"""Retry bounds for the OpenAI-compatible and SiliconFlow answer providers."""

import math
from unittest.mock import Mock, patch

import pytest

from app.services.course.chaoxing.answer_providers import AI, SiliconFlow


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload


_QUESTION = {"type": "single", "title": "中国的首都是哪里？", "options": ["A.北京", "B.上海"]}
_SUCCESS = FakeResponse({"choices": [{"message": {"content": '{"Answer": ["A"]}'}}]})
_FAILURE = FakeResponse({"error": "temporary failure"}, status_code=503)


def _build_ai(**config):
    provider = AI()
    provider.config_set(
        {
            "provider": "AI",
            "endpoint": "https://93.184.216.34/v1/chat/completions",
            "key": "test-key",
            "model": "test-model",
            "min_interval_seconds": 0,
            **config,
        }
    )
    client = Mock()
    with patch("app.services.course.chaoxing.answer_providers.ai.httpx.Client", return_value=client):
        provider.init_tiku()
    return provider, client


def _build_siliconflow(**config):
    provider = SiliconFlow()
    provider.config_set(
        {
            "provider": "SiliconFlow",
            "siliconflow_key": "test-key",
            "siliconflow_endpoint": "https://93.184.216.34/v1/chat/completions",
            "min_interval_seconds": 0,
            **config,
        }
    )
    session = Mock()
    with patch("app.services.course.chaoxing.answer_providers.siliconflow.requests.Session", return_value=session):
        provider.init_tiku()
    return provider, session


@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_zero_max_retries_still_makes_the_initial_request(builder):
    provider, request_client = builder(max_retries=0)
    request_client.post.return_value = _SUCCESS

    with (
        patch("app.services.course.chaoxing.answer_providers.ai.time.sleep") as ai_sleep,
        patch("app.services.course.chaoxing.answer_providers.siliconflow.time.sleep") as siliconflow_sleep,
    ):
        assert provider._query(_QUESTION) == "A"

    assert provider.max_retries == 1
    request_client.post.assert_called_once()
    ai_sleep.assert_not_called()
    siliconflow_sleep.assert_not_called()


@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_string_attempt_count_is_total_and_stops_on_success(builder):
    provider, request_client = builder(max_retries="3")
    request_client.post.side_effect = [_FAILURE, _SUCCESS, _SUCCESS]

    with (
        patch("app.services.course.chaoxing.answer_providers.ai.time.sleep"),
        patch("app.services.course.chaoxing.answer_providers.siliconflow.time.sleep"),
    ):
        assert provider._query(_QUESTION) == "A"

    assert provider.max_retries == 3
    assert request_client.post.call_count == 2


@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_failed_final_attempt_does_not_sleep(builder):
    provider, request_client = builder(max_retries=1)
    request_client.post.return_value = _FAILURE

    with (
        patch("app.services.course.chaoxing.answer_providers.ai.time.sleep") as ai_sleep,
        patch("app.services.course.chaoxing.answer_providers.siliconflow.time.sleep") as siliconflow_sleep,
    ):
        assert provider._query(_QUESTION) is None

    request_client.post.assert_called_once()
    ai_sleep.assert_not_called()
    siliconflow_sleep.assert_not_called()


@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_only_intermediate_failures_sleep(builder):
    provider, request_client = builder(max_retries=2)
    request_client.post.side_effect = [_FAILURE, _FAILURE]

    with (
        patch("app.services.course.chaoxing.answer_providers.ai.time.sleep") as ai_sleep,
        patch("app.services.course.chaoxing.answer_providers.siliconflow.time.sleep") as siliconflow_sleep,
    ):
        assert provider._query(_QUESTION) is None

    assert request_client.post.call_count == 2
    sleep_calls = ai_sleep.call_args_list + siliconflow_sleep.call_args_list
    assert len(sleep_calls) == 1
    assert sleep_calls[0].args == (2.0,)


@pytest.mark.parametrize("invalid", [-1, "invalid", "", None, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_invalid_attempt_count_falls_back_to_three_attempts(builder, invalid):
    provider, request_client = builder(max_retries=invalid)
    request_client.post.side_effect = [_FAILURE, _FAILURE, _FAILURE]

    with (
        patch("app.services.course.chaoxing.answer_providers.ai.time.sleep") as ai_sleep,
        patch("app.services.course.chaoxing.answer_providers.siliconflow.time.sleep") as siliconflow_sleep,
    ):
        assert provider._query(_QUESTION) is None

    assert provider.max_retries == 3
    assert request_client.post.call_count == 3
    sleep_calls = ai_sleep.call_args_list + siliconflow_sleep.call_args_list
    assert sleep_calls
    assert all(math.isfinite(call.args[0]) and call.args[0] >= 0 for call in sleep_calls)


@pytest.mark.parametrize("invalid", [-1, "invalid", "", None, "nan", "inf", "-inf", math.nan, math.inf])
@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_invalid_retry_delay_uses_finite_non_negative_default(builder, invalid):
    provider, request_client = builder(max_retries=2, retry_delay=invalid)
    request_client.post.side_effect = [_FAILURE, _FAILURE]

    with (
        patch("app.services.course.chaoxing.answer_providers.ai.time.sleep") as ai_sleep,
        patch("app.services.course.chaoxing.answer_providers.siliconflow.time.sleep") as siliconflow_sleep,
    ):
        assert provider._query(_QUESTION) is None

    assert provider.retry_delay == 2.0
    sleep_calls = ai_sleep.call_args_list + siliconflow_sleep.call_args_list
    assert sleep_calls
    assert all(math.isfinite(call.args[0]) and call.args[0] >= 0 for call in sleep_calls)


@pytest.mark.parametrize("builder", [_build_ai, _build_siliconflow])
def test_negative_or_non_finite_interval_uses_default(builder):
    provider, _request_client = builder(min_interval_seconds=-math.inf)

    expected = 3.0
    actual = provider.min_interval_seconds if isinstance(provider, AI) else provider.min_interval
    assert actual == expected
