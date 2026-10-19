"""Course protocol regressions; every remote request is replaced with a fake."""

import json
from base64 import b64decode
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.course.zhihuishu.adapter import ZhihuishuAdapter
from app.services.course.zhihuishu.auth import ZhihuishuAuth
from app.services.course.zhihuishu.crypto import VIDEO_KEY, Cipher, get_ev
from app.services.course.zhihuishu.learning import ZhihuishuLearning


def _response(payload, status_code=200):
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


def _video(**updates):
    video = {
        "video_id": 11,
        "video_sec": 10,
        "small_lesson_id": 0,
        "lesson_id": 22,
        "chapter_id": 33,
        "recruit_id": 44,
        "course_id": 55,
        "study_total_time": 0,
        "watch_state": 0,
    }
    video.update(updates)
    return video


def test_course_list_preserves_separate_recruitments_of_the_same_course():
    learning = ZhihuishuLearning({})
    learning._signed_post = Mock(
        side_effect=[
            _response(
                {
                    "code": 200,
                    "result": {
                        "totalCount": 2,
                        "courseOpenDtos": [
                            {"courseId": 1, "recruitId": 10, "secret": "current"},
                            {"courseId": 1, "recruitId": 20, "secret": "previous"},
                        ],
                    },
                }
            ),
            _response(
                {
                    "code": 200,
                    "result": {
                        "totalCount": 1,
                        "courseOpenDtos": [
                            {"courseId": 1, "recruitId": 10, "secret": "current"},
                        ],
                    },
                }
            ),
        ]
    )

    assert [c["recruitAndCourseId"] for c in learning.get_course_list()] == ["current", "previous"]


def test_video_lookup_does_not_turn_course_list_failure_into_a_raw_course_secret():
    adapter = ZhihuishuAdapter()
    adapter.learning = SimpleNamespace(
        get_course_list=Mock(side_effect=RuntimeError("session expired")), get_video_list=Mock()
    )

    with pytest.raises(RuntimeError, match="session expired"):
        adapter.get_videos("123")

    adapter.learning.get_video_list.assert_not_called()


def test_course_detail_can_resolve_the_recruitment_secret():
    adapter = ZhihuishuAdapter()
    course = {"courseId": 1, "recruitId": 20, "secret": "previous"}
    adapter.learning = SimpleNamespace(get_course_list=lambda: [course])

    assert adapter.get_course_detail("previous") == course


@pytest.mark.parametrize(
    "payload",
    [
        {"code": -1, "msg": "not logged in"},
        {"code": 500, "data": {}},
        {"message": "gateway error"},
        [],
    ],
)
def test_course_errors_are_not_successful_empty_lists(payload):
    learning = ZhihuishuLearning({})
    learning._signed_post = Mock(return_value=_response(payload))

    with pytest.raises(Exception, match="response|code|响应"):
        learning.get_course_list()


def test_video_list_errors_cannot_create_a_completed_empty_task():
    learning = ZhihuishuLearning({})
    learning.gologin = Mock()
    learning._signed_post = Mock(return_value=_response({"code": -1, "msg": "not logged in"}))
    adapter = ZhihuishuAdapter()
    adapter.learning = learning
    learning.get_course_list = lambda: [{"courseId": "1", "secret": "rac"}]

    with pytest.raises(Exception, match="response rejected"):
        adapter.start_course("1")

    assert adapter.list_tasks() == []


def test_prelearning_omits_zero_small_lesson_and_keeps_resume_fields():
    learning = ZhihuishuLearning({})
    learning._signed_post = Mock(
        return_value=_response(
            {
                "code": 0,
                "data": {
                    "studiedLessonDto": {
                        "id": 99,
                        "learnTimeSec": 4,
                        "studyTotalTime": 80,
                    }
                },
            }
        )
    )
    video = _video()

    token = learning._learning_token_id(video)

    assert b64decode(token) == b"99"
    assert "lessonVideoId" not in learning._signed_post.call_args.args[1]
    assert video["learn_time_sec"] == 4
    assert video["study_total_time"] == 80


def test_missing_learning_token_does_not_submit_progress(monkeypatch):
    monkeypatch.setattr("app.services.course.zhihuishu.learning.time.sleep", lambda *_: None)
    learning = ZhihuishuLearning({})
    learning._signed_post = Mock(return_value=_response({"code": 0, "data": {}}))
    learning._save_progress = Mock()

    with pytest.raises(Exception, match="token|Token"):
        learning.watch_video(_video())

    learning._save_progress.assert_not_called()


def test_watch_progress_keeps_cumulative_time_separate_from_video_position(monkeypatch):
    monkeypatch.setattr("app.services.course.zhihuishu.learning.time.sleep", lambda *_: None)
    learning = ZhihuishuLearning({}, uuid="uuid")
    requests = []

    def post(url, payload, **kwargs):
        requests.append((url, payload))
        if "prelearningNote" in url:
            return _response(
                {
                    "code": 0,
                    "data": {
                        "studiedLessonDto": {
                            "id": 99,
                            "learnTimeSec": 4,
                            "studyTotalTime": 80,
                        }
                    },
                }
            )
        return _response({"code": 0})

    learning._signed_post = post

    assert learning.watch_video(_video(study_total_time=80), speed=2) is True

    reports = [payload for url, payload in requests if "saveDatabase" in url]
    assert len(reports) == 1
    assert reports[0]["sdsew"] == get_ev([44, 22, 0, 11, 33, "0", 6, 86, "0:00:10", "uuidzhs"])


@pytest.mark.parametrize("code", [-8, None, False])
def test_rejected_or_missing_progress_code_is_not_completion(monkeypatch, code):
    monkeypatch.setattr("app.services.course.zhihuishu.learning.time.sleep", lambda *_: None)
    learning = ZhihuishuLearning({})
    learning._learning_token_id = lambda video: "token"
    learning._save_progress = lambda *args, **kwargs: code

    assert learning.watch_video(_video(), speed=2) is False


def test_non_success_http_progress_is_not_completion():
    learning = ZhihuishuLearning({})
    learning._signed_post = Mock(return_value=_response({"code": 0}, status_code=503))

    assert learning._save_progress(_video(), 10, 0, "0,1,2", "token") is None


def test_watch_state_does_not_apply_parent_completion_to_unmatched_small_lesson():
    adapter = ZhihuishuAdapter()
    adapter.learning = SimpleNamespace(
        query_study_info=lambda *args: {
            "lv": {},
            "lesson": {"22": {"studyTotalTime": 100, "watchState": 1}},
        }
    )
    videos = [_video(small_lesson_id=77)]

    adapter._annotate_watch_state(videos, {"recruitId": 44})

    assert videos[0]["watch_state"] == 0


def test_clearing_auth_cookies_clears_uuid():
    auth = ZhihuishuAuth()
    auth.cookies = {"CASLOGC": '{"uuid":"old-user"}'}

    auth.cookies = {}

    assert auth.uuid is None


def test_invalid_auth_cookies_do_not_replace_an_existing_identity():
    auth = ZhihuishuAuth()
    auth.cookies = {"CASLOGC": '{"uuid":"old-user"}'}

    with pytest.raises(ValueError, match="invalid"):
        auth.cookies = {"CASLOGC": "{}"}

    assert auth.cookies["CASLOGC"] == '{"uuid":"old-user"}'
    assert auth.uuid == "old-user"


def test_password_login_uses_current_gateway_callback_and_proxy():
    auth = ZhihuishuAuth(proxies={"https": "http://proxy.example"})
    auth.session = Mock()
    auth.session.cookies = {"CASLOGC": '{"uuid":"user"}'}
    auth.session.post.return_value = _response({"status": 1, "pwd": "ticket"})

    assert auth.password_login("username", "password")["CASLOGC"]

    assert auth.session.get.call_args.args[0] == "https://passport.zhihuishu.com/login"
    assert auth.session.get.call_args.kwargs["params"]["service"] == (
        "https://onlineservice-api.zhihuishu.com/gateway/f/v1/login/gologin"
        "?fromurl=https%3A%2F%2Fonlineweb.zhihuishu.com%2F"
    )
    assert auth.session.post.call_args.kwargs["proxies"] == auth.proxies


def test_explicit_zero_enrollments_can_omit_course_dtos():
    learning = ZhihuishuLearning({})
    learning._signed_post = Mock(return_value=_response({"code": 200, "result": {"totalCount": 0}}))

    assert learning.get_course_list() == []


def test_password_login_does_not_succeed_without_cookies():
    auth = ZhihuishuAuth()
    auth.session = Mock()
    auth.session.cookies = {}
    auth.session.post.return_value = _response({"status": 1, "pwd": "ticket"})

    with pytest.raises(Exception, match="No cookies found"):
        auth.password_login("username", "password")


def test_qr_login_uses_gateway_callback_and_proxy():
    auth = ZhihuishuAuth(proxies={"https": "http://proxy.example"})
    auth.session = Mock()
    auth.session.cookies = {"CASLOGC": '{"uuid":"user"}'}
    auth.session.get.side_effect = [
        _response({"qrToken": "qr-token", "img": "cXI="}),
        _response({"status": 1, "oncePassword": "ticket"}),
        _response({}),
    ]
    cancel_event = SimpleNamespace(is_set=lambda: False, wait=lambda interval: False)
    images = []

    assert auth.qr_login(images.append, cancel_event=cancel_event)["CASLOGC"]

    assert images == [b"qr"]
    assert auth.session.get.call_args.kwargs["params"]["service"].startswith(
        "https://onlineservice-api.zhihuishu.com/gateway/f/v1/login/gologin"
    )
    assert all(call.kwargs["proxies"] == auth.proxies for call in auth.session.get.call_args_list)


def test_cumulative_progress_is_monotonic_across_multiple_reports(monkeypatch):
    monkeypatch.setattr("app.services.course.zhihuishu.learning.time.sleep", lambda *_: None)
    learning = ZhihuishuLearning({}, uuid="user")
    reports = []

    def post(url, payload, **kwargs):
        if "prelearningNote" in url:
            return _response(
                {
                    "code": 0,
                    "data": {
                        "studiedLessonDto": {
                            "id": 99,
                            "learnTimeSec": 4,
                            "studyTotalTime": 80,
                        }
                    },
                }
            )
        reports.append(payload["sdsew"])
        return _response({"code": 0})

    learning._signed_post = post
    video = _video(video_sec=70)

    assert learning.watch_video(video, speed=2) is True

    assert reports == [
        get_ev([44, 22, 0, 11, 33, "0", 60, 140, "0:01:04", "userzhs"]),
        get_ev([44, 22, 0, 11, 33, "0", 6, 146, "0:01:10", "userzhs"]),
    ]
    assert video["study_total_time"] == 146
    assert video["learn_time_sec"] == 70


def test_video_cipher_pads_utf8_bytes():
    value = json.dumps({"name": "智慧树课程"}, ensure_ascii=False)
    cipher = Cipher(VIDEO_KEY)

    assert cipher.decrypt(cipher.encrypt(value)) == value
