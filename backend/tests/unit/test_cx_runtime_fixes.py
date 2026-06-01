# -*- coding: utf-8 -*-
"""Regression tests for G:cx-runtime audit findings.

Covers:
- F26: study_video 403 recovery must apply the refreshed duration (not a dead var)
- F46: study_video must have a max-iteration/time cap (no infinite loop)
- F50: quiz_service AI concurrency must surface/log worker exceptions (random fallback)
- F27: work_legacy AI futures must be collected (real concurrency + surfaced errors)
- F48: work_legacy None-guard must not dereference tiku when it is None
- F51: work_legacy completion branch dead isinstance(res, list) removed
- F47: media_service must not double-report full duration; should_stop + duration fix
- F49: live.get_status must read the top-level jobid, not a nonexistent property key
- F24: chaoxing auth_service password-login must not KeyError on unexpected JSON
"""
import types
from unittest.mock import Mock

from app.services.course.chaoxing.video_service import ChaoxingVideoService
from app.services.course.chaoxing.media_service import ChaoxingMediaService
from app.services.course.chaoxing.work_legacy_service import ChaoxingWorkLegacyService
from app.services.course.chaoxing.quiz_service import QuizAnswerProcessor
from app.services.course.chaoxing.client import StudyResult
from app.services.course.chaoxing.answer import AI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_manager(session):
    sm = Mock()
    sm.get_session.return_value = session
    sm.update_cookies.return_value = None
    return sm


def _video_service(session):
    return ChaoxingVideoService(
        get_fid_func=lambda: "fid",
        get_uid_func=lambda: "uid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
        session_manager=_make_session_manager(session),
    )


_COURSE = {"clazzId": "c1", "courseId": "co1", "cpi": "cpi1"}


def _job():
    return {
        "name": "job",
        "jobid": "j1",
        "objectid": "o1",
        "otherinfo": "nodeId_x",
        "playTime": 0,
        "rt": "1",
        "videoFaceCaptureEnc": "",
        "attDuration": "",
        "attDurationEnc": "",
    }


# ---------------------------------------------------------------------------
# F26: refreshed duration must be applied after 403 recovery
# ---------------------------------------------------------------------------

def test_f26_403_recovery_applies_refreshed_duration():
    session = Mock()
    # initial /ananas/status fetch
    init_resp = Mock()
    init_resp.json.return_value = {
        "status": "success", "dtoken": "dt0", "crc": "x", "key": "k",
        "duration": 100,
    }
    session.get.return_value = init_resp

    svc = _video_service(session)

    captured = {}

    # Pre-loop report passes-not; first in-loop report -> 403; after recovery
    # (new duration 250), the next report must carry duration=250, then pass.
    # Start play_time == duration so each in-loop report fires immediately.
    job = _job()
    job["playTime"] = 100 * 1000  # play_time == duration (100)

    calls = {"n": 0}

    def fake_log(_session, _course, _job_, _job_info, _dtoken, _duration, _playingTime, _type="Video", headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, 200  # pre-loop report: not passed, not 403
        if calls["n"] == 2:
            return False, 403  # first in-loop report -> 403, triggers recovery
        captured["duration"] = _duration
        return True, 200

    svc.video_progress_log = fake_log
    # After recovery: duration changes to 250, playTime saturated to 250 so the
    # next report fires immediately (play_time == duration), keeping the test fast.
    svc._recover_after_forbidden = lambda *a, **k: {"dtoken": "dt1", "duration": 250, "playTime": 250}

    import app.services.course.chaoxing.video_service as vs_mod
    orig_sleep = vs_mod.time.sleep
    vs_mod.time.sleep = lambda *a, **k: None
    try:
        result = svc.study_video(_COURSE, job, {}, _speed=1.0)
    finally:
        vs_mod.time.sleep = orig_sleep

    assert result == StudyResult.SUCCESS
    # The dead-variable bug kept the stale duration (100); the fix applies 250.
    assert captured["duration"] == 250


# ---------------------------------------------------------------------------
# F46: study_video must not loop forever when server never returns isPassed
# ---------------------------------------------------------------------------

def test_f46_study_video_has_iteration_cap():
    session = Mock()
    init_resp = Mock()
    init_resp.json.return_value = {
        "status": "success", "dtoken": "dt0", "crc": "x", "key": "k",
        "duration": 5,
    }
    session.get.return_value = init_resp

    svc = _video_service(session)

    # Server persistently returns 200 + isPassed False.
    svc.video_progress_log = lambda *a, **k: (False, 200)

    # Patch time.sleep so the test runs fast.
    import app.services.course.chaoxing.video_service as vs_mod
    orig_sleep = vs_mod.time.sleep
    vs_mod.time.sleep = lambda *a, **k: None
    try:
        result = svc.study_video(_COURSE, _job(), {}, _speed=1000.0)
    finally:
        vs_mod.time.sleep = orig_sleep

    # Must terminate (not hang) with a failure status, not loop forever.
    assert result in (StudyResult.ERROR, StudyResult.TIMEOUT)


# ---------------------------------------------------------------------------
# F50 / F27: AI concurrency must surface worker exceptions (random fallback)
# ---------------------------------------------------------------------------

class _AITiku(AI):
    DISABLE = False
    COVER_RATE = 0.8

    def __init__(self):
        self.DISABLE = False  # bypass real init while keeping flags sane

    def get_submit_params(self):
        return ""


def _ai_question():
    return {
        "id": "q1",
        "type": "single",
        "options": "A.one\nB.two\nC.three",
        "title": "t",
        "answerField": {},
    }


def test_f50_quiz_ai_worker_exception_falls_back(monkeypatch):
    tiku = _AITiku()

    def boom(q):
        raise RuntimeError("query exploded")

    tiku.query = boom

    proc = QuizAnswerProcessor(tiku, {"ai_concurrency": 2})
    q = _ai_question()
    questions = {"questions": [q]}

    # Must not raise; the failed question must still get an answer field filled
    # (random fallback) instead of being silently left blank.
    proc.process_questions(questions)

    assert f'answer{q["id"]}' in q["answerField"]
    assert q[f'answerSource{q["id"]}'] == "random"


def test_f27_work_legacy_study_work_ai_worker_exception_falls_back():
    """study_work's AI branch must collect futures, log the error, and fall back
    to a random answer (so the submitted form has no silently-blank fields)."""
    tiku = _AITiku()
    tiku.query = lambda q: (_ for _ in ()).throw(RuntimeError("boom"))
    tiku.COVER_RATE = 0.8
    tiku.get_submit_params = lambda: ""

    captured_form = {}

    class _Resp:
        text = "<html>question</html>"
        status_code = 200

        def json(self):
            return {"status": True, "msg": "ok"}

    class _FakeSession:
        def post(self, *a, **k):
            captured_form.update(k.get("data", {}))
            return _Resp()

    sm = Mock()
    sm.get_session.return_value = _FakeSession()

    svc = ChaoxingWorkLegacyService(tiku, rollback_times=0, kwargs={"ai_concurrency": 2}, session_manager=sm)

    q = _ai_question()
    questions = {"questions": [q]}
    # Bypass network fetch with a prepared question set.
    svc._fetch_response = lambda *a, **k: (_Resp(), questions)

    # Must not raise even though every worker raises.
    result = svc.study_work(_COURSE, _job(), {})

    assert result == StudyResult.SUCCESS
    # The failing question must still have an answer field (random fallback), not blank.
    assert f'answer{q["id"]}' in q["answerField"]
    assert q[f'answerSource{q["id"]}'] == "random"


# ---------------------------------------------------------------------------
# F48: reversed None-guard must not dereference tiku when None
# ---------------------------------------------------------------------------

def test_f48_study_work_none_tiku_guard():
    svc = ChaoxingWorkLegacyService(tiku=None, rollback_times=0, kwargs={})
    # Must short-circuit cleanly, not raise AttributeError on None.DISABLE.
    result = svc.study_work(_COURSE, _job(), {})
    assert result == StudyResult.SUCCESS


# ---------------------------------------------------------------------------
# F47: media_service must not double-report full duration; should_stop honored
# ---------------------------------------------------------------------------

def _media_job():
    j = _job()
    j["property"] = {
        "akid": "a", "userid": "u", "isdrag": "0", "rt": "1", "dtype": "Video",
    }
    return j


def test_f47_media_no_double_full_duration_report():
    session = Mock()
    init_resp = Mock()
    init_resp.json.return_value = {
        "status": "success", "dtoken": "dt", "crc": "x", "key": "k", "duration": 100,
    }
    session.get.return_value = init_resp

    svc = ChaoxingMediaService(
        get_fid_func=lambda: "fid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
        session_manager=_make_session_manager(session),
    )

    reported_playtimes = []

    def fake_log(_session, _course, _job_, _job_info, _dtoken, duration, play_time, _type, headers=None):
        reported_playtimes.append(play_time)
        return True, 200  # pass immediately so we only see the pre-loop reports

    svc.video_progress_log = fake_log

    result = svc.study_video(_COURSE, _media_job(), {})
    assert result is True
    # Exactly one pre-loop report, and it must NOT claim the full duration was watched.
    assert reported_playtimes == [0]
    assert 100 not in reported_playtimes


def test_f47_media_should_stop_honored():
    session = Mock()
    init_resp = Mock()
    init_resp.json.return_value = {
        "status": "success", "dtoken": "dt", "crc": "x", "key": "k", "duration": 100,
    }
    session.get.return_value = init_resp

    svc = ChaoxingMediaService(
        get_fid_func=lambda: "fid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
        session_manager=_make_session_manager(session),
    )
    svc.video_progress_log = lambda *a, **k: (False, 200)

    # should_stop True after the initial report -> loop must exit, not hang.
    result = svc.study_video(_COURSE, _media_job(), {}, should_stop=lambda: True)
    assert result is False


# ---------------------------------------------------------------------------
# F49: live.get_status must send the real top-level jobid
# ---------------------------------------------------------------------------

def test_f49_live_get_status_uses_top_level_jobid(monkeypatch):
    import app.services.course.chaoxing.live as live_mod

    captured = {}

    class _FakeResp:
        text = '{"ok": 1}'

        def raise_for_status(self):
            pass

    class _FakeSession:
        def get(self, url, headers=None, timeout=None):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(live_mod.SessionManager, "get_session", staticmethod(lambda: _FakeSession()))

    attachment = {
        "jobid": "JOB-123",
        "property": {"liveId": "L1", "title": "t"},
    }
    defaults = {"userid": "u1", "clazzId": "c1", "knowledgeid": "k1"}
    live = live_mod.Live(attachment, defaults, course_id="co1")
    live.get_status()

    assert "jobid=JOB-123" in captured["url"]
    assert "jobid=&" not in captured["url"]


# ---------------------------------------------------------------------------
# F24: password-login must not KeyError on unexpected JSON
# ---------------------------------------------------------------------------

def test_f24_password_login_unexpected_json_no_keyerror(monkeypatch):
    from app.services.course.chaoxing.auth_service import ChaoxingAuthService
    import app.services.course.chaoxing.auth_service as auth_mod

    account = types.SimpleNamespace(username="u", password="p")
    svc = ChaoxingAuthService(account=account, session_manager=_make_session_manager(Mock()))
    svc.cipher = Mock()
    svc.cipher.encrypt.return_value = "enc"

    class _Resp:
        # JSON missing both 'status' and 'msg2' (e.g. captcha/risk-control envelope)
        def json(self):
            return {"error": "captcha required"}

    class _FakeSession:
        def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(auth_mod.requests, "Session", lambda: _FakeSession())

    # Must return a clean failure dict, not raise KeyError.
    result = svc.login(login_with_cookies=False)
    assert result["status"] is False
    assert isinstance(result["msg"], str)
