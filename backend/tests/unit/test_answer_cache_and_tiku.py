"""Regression tests for answer cache, Tiku flags/judgement, AI answer validation,
decode SSRF guard, and the vision_ocr shim.

Covers audit findings F10, F11, F12/F16/F35, F13, F28, F29, F30, F52, F53.
"""
import importlib
import os
from unittest.mock import Mock, patch



# ---------------------------------------------------------------------------
# Cache: writable default path + write-through persistence (F11, F12, F16, F30, F35)
# ---------------------------------------------------------------------------

def _fresh_cache_module():
    import app.services.course.chaoxing.answer_cache as mod
    importlib.reload(mod)
    return mod


def test_cache_default_path_is_writable_tmp(monkeypatch):
    monkeypatch.delenv("CHAOXING_CACHE_FILE", raising=False)
    mod = _fresh_cache_module()
    # Default must not resolve to a relative path under the (read-only) CWD.
    assert mod.DEFAULT_CACHE_FILE.startswith("/tmp"), mod.DEFAULT_CACHE_FILE


def test_cache_default_path_env_overridable(tmp_path, monkeypatch):
    target = tmp_path / "answer_cache.json"
    monkeypatch.setenv("CHAOXING_CACHE_FILE", str(target))
    mod = _fresh_cache_module()
    assert mod.DEFAULT_CACHE_FILE == str(target)


def test_add_cache_is_write_through_persistent(tmp_path):
    """add_cache must survive across new CacheDAO instances (F11/F30)."""
    from app.services.course.chaoxing.answer_cache import CacheDAO

    cache_file = str(tmp_path / "cache.json")
    dao1 = CacheDAO(cache_file)
    dao1.add_cache("Q1", "A1")

    # A brand-new DAO (as constructed per-question in answer_base.query) must see it.
    dao2 = CacheDAO(cache_file)
    assert dao2.get_cache("Q1") == "A1"


def test_add_cache_effective_in_memory_even_if_disk_write_fails(tmp_path):
    """On a read-only rootfs the disk write fails, but the second identical
    question must still be served from the in-memory snapshot (F35/F16)."""
    from app.services.course.chaoxing.answer_cache import CacheDAO

    cache_file = str(tmp_path / "cache.json")
    dao = CacheDAO(cache_file)
    with patch.object(CacheDAO, "_write_cache", side_effect=OSError("read-only fs")):
        # add_cache must not raise even when the disk is read-only.
        dao.add_cache("Q1", "A1")
    # Same-process re-query (even a fresh DAO) hits the shared snapshot.
    assert CacheDAO(cache_file).get_cache("Q1") == "A1"


def test_get_cache_does_not_reread_file_every_call(tmp_path):
    """Per-question lookups must not re-parse the whole file (F29)."""
    from app.services.course.chaoxing.answer_cache import CacheDAO

    cache_file = str(tmp_path / "cache.json")
    dao = CacheDAO(cache_file)
    dao.add_cache("Q1", "A1")

    with patch.object(CacheDAO, "_read_cache", wraps=dao._read_cache) as spy:
        for _ in range(20):
            dao.get_cache("Q1")
        # In-memory snapshot should mean zero (or at most one) disk reads here.
        assert spy.call_count == 0


# ---------------------------------------------------------------------------
# Tiku flags must be per-instance (F53)
# ---------------------------------------------------------------------------

def test_tiku_flags_are_instance_attributes():
    from app.services.course.chaoxing.answer_base import Tiku

    a = Tiku()
    b = Tiku()
    a.DISABLE = True
    a.COVER_RATE = 0.5
    a.true_list = ["yes"]
    # b must be unaffected by mutations on a
    assert b.DISABLE is False
    assert b.COVER_RATE == 0.8
    assert b.true_list == []
    # and the lists must be distinct objects (no shared mutable default)
    assert a.true_list is not b.true_list
    assert a.false_list is not b.false_list


# ---------------------------------------------------------------------------
# Judgement true_list / false_list applied independently (F52)
# ---------------------------------------------------------------------------

def test_judgement_lists_applied_independently():
    from app.services.course.chaoxing.answer_base import Tiku

    t = Tiku()
    t.config_set({"provider": "x", "true_list": "正确"})  # only true_list configured
    t.init_tiku()
    assert "正确" in t.true_list
    # false_list defaulted, not discarded-into-empty
    assert t.false_list, "false_list should fall back to defaults when not configured"


def test_judgement_only_false_list_configured():
    from app.services.course.chaoxing.answer_base import Tiku

    t = Tiku()
    t.config_set({"provider": "x", "false_list": "错误"})
    t.init_tiku()
    assert "错误" in t.false_list
    assert t.true_list, "true_list should fall back to defaults when not configured"


# ---------------------------------------------------------------------------
# AI judgement answer validated/normalized before caching (F28)
# ---------------------------------------------------------------------------

def test_ai_judgement_sentence_not_cached_and_normalized():
    """An AI judgement answer that is a sentence (not 正确/错误) must NOT be
    blindly accepted+cached, since downstream judgement_select would random-pick."""
    from app.services.course.chaoxing.answer_providers import AI

    ai = AI()
    ai.config_set({"provider": "AI"})
    # Set judgement lists manually (init_tiku path)
    ai.true_list = ["正确", "对", "T"]
    ai.false_list = ["错误", "错", "F"]
    ai.DISABLE = False

    captured = {}

    def fake_query(q):
        return "这道题表述是对的"

    with patch.object(AI, "_query", side_effect=fake_query):
        with patch("app.services.course.chaoxing.answer_cache.CacheDAO.add_cache") as add:
            result = ai.query({"title": "判断题 1+1=2", "type": "judgement"})
            # Either normalized into the true_list value, or rejected (None).
            if result is not None:
                assert result in ai.true_list + ai.false_list, result
            # An unmappable judgement sentence must not be cached verbatim.
            for call in add.call_args_list:
                cached_answer = call.args[1]
                assert cached_answer in ai.true_list + ai.false_list


def test_ai_normal_completion_answer_still_accepted():
    from app.services.course.chaoxing.answer_providers import AI

    ai = AI()
    ai.config_set({"provider": "AI"})
    ai.true_list = ["正确"]
    ai.false_list = ["错误"]
    ai.DISABLE = False

    with patch.object(AI, "_query", return_value="输入/输出"):
        result = ai.query({"title": "完成这道填空", "type": "completion"})
        assert result == "输入/输出"


# ---------------------------------------------------------------------------
# SSRF guard in decode._ocr_image_to_text (F10)
# ---------------------------------------------------------------------------

def test_decode_ocr_rejects_non_allowlisted_host(monkeypatch):
    monkeypatch.setenv("CHAOXING_ENABLE_OCR", "1")
    import app.services.course.chaoxing.decode as decode
    importlib.reload(decode)

    with patch.object(decode.requests, "Session") as sess_cls:
        # internal/metadata host must be blocked before any GET
        result = decode._ocr_image_to_text("http://169.254.169.254/latest/meta-data/")
        assert result == ""
        sess_cls.return_value.get.assert_not_called()


def test_decode_ocr_allows_chaoxing_host(monkeypatch):
    monkeypatch.setenv("CHAOXING_ENABLE_OCR", "1")
    import app.services.course.chaoxing.decode as decode
    importlib.reload(decode)

    fake_resp = Mock()
    fake_resp.status_code = 404  # short-circuit after the GET; we only assert it was attempted
    fake_session = Mock()
    fake_session.get.return_value = fake_resp
    fake_session.headers = {}
    fake_session.cookies = Mock()

    with patch.object(decode.requests, "Session", return_value=fake_session):
        decode._ocr_image_to_text("https://p.ananas.chaoxing.com/star3/abc.png")
        assert fake_session.get.called
        # redirects must be disabled to prevent allowlist bypass via redirect
        _, kwargs = fake_session.get.call_args
        assert kwargs.get("allow_redirects") is False


def test_decode_ocr_rejects_non_https_scheme(monkeypatch):
    monkeypatch.setenv("CHAOXING_ENABLE_OCR", "1")
    import app.services.course.chaoxing.decode as decode
    importlib.reload(decode)

    with patch.object(decode.requests, "Session") as sess_cls:
        result = decode._ocr_image_to_text("http://p.ananas.chaoxing.com/star3/abc.png")
        # http (non-https) to even an allowlisted host should be rejected
        assert result == ""
        sess_cls.return_value.get.assert_not_called()


# ---------------------------------------------------------------------------
# vision_ocr shim wires through to the real implementation (F13)
# ---------------------------------------------------------------------------

def test_vision_ocr_shim_reexports_real_impl():
    import api.vision_ocr as shim
    from app.services.course.common import ocr as real

    assert shim.vision_ocr is real.vision_ocr
    assert shim.is_vision_ocr_enabled is real.is_vision_ocr_enabled


@patch.dict(os.environ, {"CHAOXING_VISION_OCR_PROVIDER": "openai", "CHAOXING_VISION_OCR_KEY": "k"})
def test_vision_ocr_shim_enabled_when_configured():
    from app.services.course.common.ocr import reset_vision_ocr_config
    import api.vision_ocr as shim

    reset_vision_ocr_config()
    try:
        assert shim.is_vision_ocr_enabled() is True
    finally:
        reset_vision_ocr_config()
