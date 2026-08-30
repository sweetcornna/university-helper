"""Regression tests for non-object JSON values in the answer cache."""

import json

import pytest

from app.services.course.chaoxing.answer_cache import CacheDAO


def test_json_object_cache_is_read(tmp_path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(json.dumps({"Q1": "A1"}), encoding="utf8")

    assert CacheDAO(str(cache_file)).get_cache("Q1") == "A1"


@pytest.mark.parametrize("cache_value", [[], None, "not an object", 42])
def test_non_object_json_cache_is_a_miss(tmp_path, cache_value):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(json.dumps(cache_value), encoding="utf8")

    assert CacheDAO(str(cache_file)).get_cache("Q1") is None
