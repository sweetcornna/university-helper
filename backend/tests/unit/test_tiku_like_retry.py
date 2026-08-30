"""Regression tests for TikuLike retry configuration and request bounds."""

from unittest.mock import patch

import pytest

from app.services.course.chaoxing.answer_providers import TikuLike


class FakeResponse:
    status_code = 200
    text = "{}"

    def __init__(self, payload):
        self.payload = payload
        self.text = str(payload)

    def json(self):
        return self.payload


def _question():
    return {"type": "single", "title": "中国的首都是哪里？", "options": ["A.北京", "B.上海"]}


def _hit_response():
    return FakeResponse(
        {
            "code": 1,
            "results": {"output": {"questionType": "CHOICE", "answer": {"selectedOptions": ["A"]}}},
        }
    )


def _miss_response():
    return FakeResponse({"code": 0, "message": "未找到"})


def _build_like(**config):
    like = TikuLike()
    like.config_set({"tokens": "test-token", **config})
    with patch.object(like, "update_times"):
        like.init_tiku()
    # init_tiku's balance refresh is mocked; give the test token usable credit.
    like._balance = {"test-token": 10}
    return like


@pytest.mark.parametrize("retry_value", [False, "false", 0, "0"])
def test_retry_disabled_still_makes_one_request(retry_value):
    like = _build_like(likeapi_retry=retry_value, likeapi_retry_times=3)

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        return_value=_hit_response(),
    ) as post:
        assert like._query(_question()) == "A"

    assert like._retry is False
    post.assert_called_once()


def test_zero_retry_times_is_one_total_attempt():
    like = _build_like(likeapi_retry=True, likeapi_retry_times=0)

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        return_value=_miss_response(),
    ) as post:
        assert like._query(_question()) is None

    assert like._retry_times == 1
    post.assert_called_once()


def test_string_retry_times_controls_total_attempts_and_stops_on_success():
    like = _build_like(likeapi_retry="true", likeapi_retry_times="3")

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        side_effect=[_miss_response(), _hit_response(), _hit_response()],
    ) as post:
        assert like._query(_question()) == "A"

    assert like._retry is True
    assert like._retry_times == 3
    assert post.call_count == 2


@pytest.mark.parametrize("retry_times", ["invalid", "", -1, None])
def test_invalid_retry_times_falls_back_to_default(retry_times):
    like = _build_like(likeapi_retry=True, likeapi_retry_times=retry_times)

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        side_effect=[_miss_response(), _miss_response(), _miss_response()],
    ) as post:
        assert like._query(_question()) is None

    assert like._retry_times == 3
    assert post.call_count == 3


def test_invalid_retry_flag_falls_back_to_enabled():
    like = _build_like(likeapi_retry="not-a-bool", likeapi_retry_times="3")

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        side_effect=[_miss_response(), _hit_response()],
    ) as post:
        assert like._query(_question()) == "A"

    assert like._retry is True
    assert post.call_count == 2


@pytest.mark.parametrize(
    ("config_key", "attribute", "payload_key"),
    [
        ("likeapi_search", "_search", "search"),
        ("likeapi_vision", "_vision", "vision"),
    ],
)
@pytest.mark.parametrize("value", [False, "false", 0, "0", "no", "off"])
def test_likeapi_false_values_disable_request_flags(config_key, attribute, payload_key, value):
    like = _build_like(**{config_key: value})

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        return_value=_hit_response(),
    ) as post:
        assert like._query(_question()) == "A"

    assert getattr(like, attribute) is False
    assert post.call_args.kwargs["json"][payload_key] is False


@pytest.mark.parametrize(
    ("config_key", "attribute", "payload_key"),
    [
        ("likeapi_search", "_search", "search"),
        ("likeapi_vision", "_vision", "vision"),
    ],
)
@pytest.mark.parametrize("value", [True, "true", "yes", "y", "on", 1, "1"])
def test_likeapi_true_values_enable_request_flags(config_key, attribute, payload_key, value):
    like = _build_like(**{config_key: value})

    with patch(
        "app.services.course.chaoxing.answer_providers.like.requests.post",
        return_value=_hit_response(),
    ) as post:
        assert like._query(_question()) == "A"

    assert getattr(like, attribute) is True
    assert post.call_args.kwargs["json"][payload_key] is True


@pytest.mark.parametrize(
    ("config_key", "attribute", "default"),
    [
        ("likeapi_search", "_search", False),
        ("likeapi_vision", "_vision", True),
    ],
)
def test_likeapi_invalid_values_keep_safe_defaults(config_key, attribute, default):
    like = _build_like(**{config_key: "not-a-bool"})

    assert getattr(like, attribute) is default
