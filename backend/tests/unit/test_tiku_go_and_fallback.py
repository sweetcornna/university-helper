"""Tests for the ported GO题库 (TikuGo), the multi-题库 fallback chain
(TikuFallback), the LocalCache provider, and the CSV-aware tiku factory.

Brings the answer module to parity with upstream Samueli924/chaoxing while
respecting this fork's per-instance multi-tenant isolation and AI judgement
normalization.
"""

from unittest.mock import patch


class FakeResp:
    def __init__(self, json_data, status=200):
        self._j = json_data
        self.status_code = status
        self.text = str(json_data)

    def json(self):
        return self._j


# ---------------------------------------------------------------------------
# TikuGo — GO题库 (网课小工具, q.icodef.com)
# ---------------------------------------------------------------------------


def _q(title="中国的首都是哪里？", qtype="single", options="A.北京\nB.上海"):
    return {"title": title, "type": qtype, "options": options}


def test_tikugo_hit_returns_answer():
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    with patch(
        "app.services.course.chaoxing.answer_providers.go.requests.post",
        return_value=FakeResp({"code": 1, "data": "北京", "msg": ""}),
    ):
        assert go._query(_q()) == "北京"


def test_tikugo_miss_returns_none():
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    with patch(
        "app.services.course.chaoxing.answer_providers.go.requests.post",
        return_value=FakeResp({"code": 0, "data": "", "msg": "未找到"}),
    ):
        assert go._query(_q()) is None


def test_tikugo_placeholder_answer_discarded():
    """GO题库 returns '李恒雅正在努力撰写中...' as a not-found placeholder."""
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    with patch(
        "app.services.course.chaoxing.answer_providers.go.requests.post",
        return_value=FakeResp({"code": 1, "data": "李恒雅正在努力撰写中", "msg": ""}),
    ):
        assert go._query(_q()) is None


def test_tikugo_throttle_then_success():
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    responses = [
        FakeResp({"code": 0, "data": "", "msg": "流控限制，请稍后"}),
        FakeResp({"code": 1, "data": "北京", "msg": ""}),
    ]
    with (
        patch("app.services.course.chaoxing.answer_providers.go.time.sleep"),
        patch("app.services.course.chaoxing.answer_providers.go.requests.post", side_effect=responses),
    ):
        assert go._query(_q()) == "北京"


def test_tikugo_strips_bracket_prefix_and_hits():
    """The raw 【...】-prefixed title must MISS so only the stripped title can HIT,
    proving the prefix-stripping path is load-bearing."""
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    responses = [
        FakeResp({"code": 0, "data": "", "msg": "未找到"}),  # raw "【单选题】..." misses
        FakeResp({"code": 1, "data": "北京", "msg": ""}),  # stripped title hits
    ]
    with (
        patch("app.services.course.chaoxing.answer_providers.go.time.sleep"),
        patch("app.services.course.chaoxing.answer_providers.go.requests.post", side_effect=responses) as post,
    ):
        assert go._query(_q(title="【单选题】中国的首都是哪里？")) == "北京"
        assert post.call_count == 2
        assert post.call_args_list[1].kwargs["data"] == {"question": "中国的首都是哪里？"}


def test_tikugo_non_dict_json_returns_none():
    """A valid-JSON-but-non-object body must not crash; it is treated as a miss."""
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    for body in (["x"], "oops", 42, None, True):
        with patch("app.services.course.chaoxing.answer_providers.go.requests.post", return_value=FakeResp(body)):
            assert go._query(_q()) is None


def test_tikugo_init_applies_config():
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    go.config_set(
        {
            "provider": "TikuGo",
            "go_authorization": "tok",
            "go_min_interval": "2.5",
            "go_retry_times": "5",
            "go_retry_backoff": "0.5",
        }
    )
    go.init_tiku()
    assert go._headers["Authorization"] == "tok"
    assert go._min_interval == 2.5
    assert go._retry_times == 5
    assert go._retry_backoff == 0.5


def test_tikugo_init_invalid_values_keep_defaults():
    from app.services.course.chaoxing.answer_providers import TikuGo

    go = TikuGo()
    go.config_set(
        {
            "provider": "TikuGo",
            "go_retry_times": "0",
            "go_min_interval": "-1",
            "go_retry_backoff": "abc",
        }
    )
    go.init_tiku()
    assert go._min_interval == 1.0
    assert go._retry_times == 3
    assert go._retry_backoff == 1.2
    assert go._headers["Authorization"] == ""  # go_authorization optional


# ---------------------------------------------------------------------------
# TikuFallback — 多题库回退
# ---------------------------------------------------------------------------


def _fake_provider(answer, name="fake"):
    from app.services.course.chaoxing.answer_base import Tiku

    class FakeProvider(Tiku):
        def __init__(self):
            super().__init__()
            self.name = name
            self.true_list = ["正确"]
            self.false_list = ["错误"]
            self.calls = 0

        def _query(self, q_info):
            self.calls += 1
            return answer

    return FakeProvider()


def test_fallback_first_hit_wins():
    from app.services.course.chaoxing.answer_base import TikuFallback

    p1 = _fake_provider("A", "p1")
    p2 = _fake_provider("B", "p2")
    fb = TikuFallback([p1, p2])
    fb.DISABLE = False
    assert fb._query(_q()) == "A"
    assert p2.calls == 0  # second provider must not be consulted on a hit


def test_fallback_falls_through_on_miss():
    from app.services.course.chaoxing.answer_base import TikuFallback

    p1 = _fake_provider(None, "p1")
    p2 = _fake_provider("B", "p2")
    fb = TikuFallback([p1, p2])
    fb.DISABLE = False
    assert fb._query(_q()) == "B"
    assert p1.calls == 1 and p2.calls == 1


def test_fallback_falls_through_on_type_mismatch():
    from app.services.course.chaoxing.answer_base import TikuFallback

    # A judgement answer that is neither 正确 nor 错误 fails check_answer → fall through.
    p1 = _fake_provider("一段废话", "p1")
    p2 = _fake_provider("正确", "p2")
    fb = TikuFallback([p1, p2])
    fb.DISABLE = False
    assert fb._query(_q(qtype="judgement")) == "正确"


def test_fallback_ai_judgement_is_normalized():
    from app.services.course.chaoxing.answer_base import TikuFallback
    from app.services.course.chaoxing.answer_providers import AI

    ai = AI()
    ai.true_list = ["正确"]
    ai.false_list = ["错误"]
    ai._query = lambda q_info: "这道题表述是对的"
    fb = TikuFallback([ai])
    fb.DISABLE = False
    assert fb._query(_q(qtype="judgement")) == "正确"


def test_fallback_ai_non_judgement_accepts_any_nonempty():
    from app.services.course.chaoxing.answer_base import TikuFallback
    from app.services.course.chaoxing.answer_providers import AI

    ai = AI()
    ai._query = lambda q_info: "输入/输出"
    fb = TikuFallback([ai])
    fb.DISABLE = False
    assert fb._query(_q(qtype="completion")) == "输入/输出"


def test_fallback_all_miss_returns_none():
    from app.services.course.chaoxing.answer_base import TikuFallback

    fb = TikuFallback([_fake_provider(None, "p1"), _fake_provider(None, "p2")])
    fb.DISABLE = False
    assert fb._query(_q()) is None


def test_fallback_falls_through_on_query_exception():
    """A provider that raises AT QUERY TIME must be swallowed and the chain
    continues (the core resilience guarantee of the fallback)."""
    from app.services.course.chaoxing.answer_base import Tiku, TikuFallback

    class Raiser(Tiku):
        def __init__(self):
            super().__init__()
            self.name = "raiser"
            self.calls = 0

        def _query(self, q_info):
            self.calls += 1
            raise RuntimeError("net")

    raiser = Raiser()
    ok = _fake_provider("B", "ok")
    fb = TikuFallback([raiser, ok])
    fb.DISABLE = False
    assert fb._query(_q()) == "B"
    assert raiser.calls == 1 and ok.calls == 1


def test_fallback_query_keeps_multitoken_single_ai_answer():
    """Through the PUBLIC query() (what consumers call), a chain ending in AI must
    keep a valid multi-token single-choice answer — base query() must NOT re-run
    strict check_answer on a fallback result. Regression guard for the double-
    validation bug."""
    from app.services.course.chaoxing.answer_base import TikuFallback
    from app.services.course.chaoxing.answer_providers import AI

    ai = AI()
    ai.true_list = ["正确"]
    ai.false_list = ["错误"]
    ai._query = lambda q_info: "Babbage machine"
    fb = TikuFallback([ai])
    fb.DISABLE = False
    with (
        patch("app.services.course.chaoxing.answer_base.CacheDAO.get_cache", return_value=None),
        patch("app.services.course.chaoxing.answer_base.CacheDAO.add_cache"),
    ):
        assert fb.query(_q(qtype="single")) == "Babbage machine"


def test_fallback_init_drops_disabled_provider():
    """A provider that disables itself during init WITHOUT raising (e.g. a
    token-less TikuLike) must be dropped from the chain."""
    from app.services.course.chaoxing.answer_base import Tiku, TikuFallback
    from app.services.course.chaoxing.answer_providers import TikuLocalCache

    class QuietDisable(Tiku):
        def __init__(self):
            super().__init__()
            self.name = "quietdisable"

        def _init_tiku(self):
            self.DISABLE = True  # disables itself WITHOUT raising

        def _query(self, q_info):
            return None

    ok = TikuLocalCache()
    fb = TikuFallback([QuietDisable(), ok])
    fb.config_set({"provider": "x"})
    fb.init_tiku()
    assert fb.DISABLE is False
    assert fb.providers == [ok]


def test_wants_concurrent_query():
    """Only AI (directly or as a link in a chain) opts into concurrent answering."""
    from app.services.course.chaoxing.answer_base import TikuFallback
    from app.services.course.chaoxing.answer_providers import AI, SiliconFlow, TikuGo, TikuLocalCache

    assert AI().wants_concurrent_query is True
    assert SiliconFlow().wants_concurrent_query is False
    assert TikuGo().wants_concurrent_query is False
    assert TikuFallback([TikuGo(), AI()]).wants_concurrent_query is True
    assert TikuFallback([TikuGo(), TikuLocalCache()]).wants_concurrent_query is False


def test_fallback_init_drops_failing_provider():
    from app.services.course.chaoxing.answer_base import Tiku, TikuFallback
    from app.services.course.chaoxing.answer_providers import TikuLocalCache

    class FailInit(Tiku):
        def __init__(self):
            super().__init__()
            self.name = "failinit"

        def _init_tiku(self):
            raise ValueError("boom")

        def _query(self, q_info):
            return None

    ok = TikuLocalCache()
    fb = TikuFallback([FailInit(), ok])
    fb.config_set({"provider": "x"})
    fb.init_tiku()
    assert fb.DISABLE is False
    assert fb.providers == [ok]


def test_fallback_all_init_fail_disables():
    from app.services.course.chaoxing.answer_base import Tiku, TikuFallback

    class FailInit(Tiku):
        def __init__(self):
            super().__init__()
            self.name = "failinit"

        def _init_tiku(self):
            raise ValueError("boom")

        def _query(self, q_info):
            return None

    fb = TikuFallback([FailInit(), FailInit()])
    fb.config_set({"provider": "x"})
    fb.init_tiku()
    assert fb.DISABLE is True


# ---------------------------------------------------------------------------
# Factory — CSV provider parsing
# ---------------------------------------------------------------------------


def _factory(provider):
    from app.services.course.chaoxing.answer_base import Tiku

    t = Tiku()
    t.config_set({"provider": provider})
    return t.get_tiku_from_config()


def test_factory_single_localcache():
    from app.services.course.chaoxing.answer_providers import TikuLocalCache

    r = _factory("LocalCache")
    assert isinstance(r, TikuLocalCache)
    assert r.DISABLE is False


def test_factory_single_tikugo():
    from app.services.course.chaoxing.answer_providers import TikuGo

    assert isinstance(_factory("TikuGo"), TikuGo)


def test_factory_csv_builds_fallback_chain():
    from app.services.course.chaoxing.answer_base import TikuFallback
    from app.services.course.chaoxing.answer_providers import TikuGo, TikuLocalCache

    r = _factory("LocalCache,TikuGo")
    assert isinstance(r, TikuFallback)
    assert [type(p) for p in r.providers] == [TikuLocalCache, TikuGo]


def test_factory_unknown_provider_disables():
    assert _factory("Nope").DISABLE is True


def test_factory_csv_with_unknown_disables():
    assert _factory("LocalCache,Nope").DISABLE is True


def test_factory_empty_provider_disables():
    # Frontend sends '' when all 题库 are deselected ([].join(',')).
    assert _factory("").DISABLE is True


def test_factory_whitespace_or_comma_only_disables():
    # Exercises the `if not names` branch in get_tiku_from_config.
    assert _factory("   ").DISABLE is True
    assert _factory(",").DISABLE is True


# ---------------------------------------------------------------------------
# TikuLocalCache — 本地缓存题库
# ---------------------------------------------------------------------------


def test_localcache_query_always_none():
    from app.services.course.chaoxing.answer_providers import TikuLocalCache

    assert TikuLocalCache()._query(_q()) is None


def test_localcache_serves_cached_answer():
    from app.services.course.chaoxing.answer_providers import TikuLocalCache

    lc = TikuLocalCache()
    lc.config_set({"provider": "LocalCache"})
    lc.init_tiku()
    # Patch where query() actually looks it up (answer_base's bound CacheDAO),
    # which is robust even if another test reloaded the answer_cache module.
    with patch("app.services.course.chaoxing.answer_base.CacheDAO.get_cache", return_value="已缓存答案"):
        assert lc.query(_q()) == "已缓存答案"


def test_localcache_uncached_returns_none():
    from app.services.course.chaoxing.answer_providers import TikuLocalCache

    lc = TikuLocalCache()
    lc.config_set({"provider": "LocalCache"})
    lc.init_tiku()
    # Patch where query() actually looks it up (answer_base's bound CacheDAO),
    # which is robust even if another test reloaded the answer_cache module.
    with patch("app.services.course.chaoxing.answer_base.CacheDAO.get_cache", return_value=None):
        assert lc.query(_q()) is None
