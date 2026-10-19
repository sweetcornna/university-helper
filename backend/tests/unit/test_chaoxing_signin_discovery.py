"""Regression coverage for the Chaoxing course -> activity -> pre-sign chain.

Protocol reference: cxOrz/chaoxing-signin at
946df7ce94a749450894dcf243bca4eaec891db0, functions/user.ts and activity.ts.
All upstream requests and sign submissions in these tests are mocked.
"""

import json
from unittest.mock import Mock

import pytest
import requests

import app.services.course.chaoxing.signin as signin_module
from app.services.course.chaoxing.signin import (
    ACTIVE_LIST_URL,
    COURSE_LIST_URL,
    INTERACTION_URL,
    PPT_ACTIVE_INFO_URL,
    PRE_SIGN_URL,
    SIGN_ANALYSIS2_URL,
    SIGN_ANALYSIS_URL,
    ChaoxingSigninClient,
    ChaoxingSigninManager,
    SigninSessionExpiredError,
)


def _response(payload=None, *, text=None, url=ACTIVE_LIST_URL, status=200):
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.encoding = "utf-8"
    response._content = (json.dumps(payload) if text is None else text).encode()
    return response


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(signin_module.task_store, "list_tasks", lambda *args, **kwargs: [])
    monkeypatch.setattr(signin_module.task_store, "list_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(signin_module.task_store, "upsert_task", lambda *args, **kwargs: True)
    monkeypatch.setattr(signin_module.task_store, "append_history", lambda *args, **kwargs: None)
    return ChaoxingSigninManager()


@pytest.mark.parametrize(
    "payload",
    [
        {"result": False, "errorMsg": "操作太频繁，请稍后再试", "data": None},
        {"result": True, "data": None},
        {"data": {}},
        {"data": {"activeList": None}},
        {"data": {"activeList": "unexpected"}},
        {"data": {"activeList": [None]}},
    ],
)
def test_activity_error_payload_is_not_an_empty_scan(monkeypatch, payload):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response(payload)))

    with pytest.raises(requests.RequestException):
        client._get_course_activity_list("100", "200")


def test_successful_empty_activity_list_is_a_valid_empty_scan(monkeypatch):
    client = ChaoxingSigninClient()
    get = Mock(return_value=_response({"result": True, "data": {"activeList": []}}))
    monkeypatch.setattr(client.session, "get", get)

    assert client._get_course_activity_list("100", "200") == []
    assert get.call_args.args == (ACTIVE_LIST_URL,)
    assert get.call_args.kwargs["params"]["courseId"] == "100"
    assert get.call_args.kwargs["params"]["classId"] == "200"


@pytest.mark.parametrize(
    "response",
    [
        _response({"result": False, "errorMsg": "请先登录", "data": None}),
        _response(text='<html><input id="phone"><input id="pwd"></html>'),
        _response(text="login", url="https://passport2.chaoxing.com/login"),
        _response(text="", status=401),
    ],
)
def test_expired_session_is_distinct_from_no_signin(monkeypatch, response):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=response))

    with pytest.raises(SigninSessionExpiredError, match="登录已失效"):
        client._get_course_activity_list("100", "200")


def test_login_bootstrap_redirect_that_returns_to_activities_is_not_expiry(monkeypatch):
    client = ChaoxingSigninClient()
    response = _response({"result": True, "data": {"activeList": []}})
    redirect = _response(text="", status=302)
    redirect.headers["Location"] = "https://passport2.chaoxing.com/login?refer=mobilelearn"
    response.history = [redirect]
    monkeypatch.setattr(client.session, "get", Mock(return_value=response))

    assert client._get_course_activity_list("100", "200") == []


def test_course_network_failure_is_not_an_empty_course_list(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response(text='<ul class="file-list"></ul>')))
    monkeypatch.setattr(client.session, "post", Mock(side_effect=requests.Timeout("course timeout")))

    with pytest.raises(requests.Timeout, match="course timeout"):
        client.get_courses()


def test_folder_network_failure_is_not_an_empty_course_list(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client.session, "get", Mock(side_effect=requests.Timeout("folder timeout")))

    with pytest.raises(requests.Timeout, match="folder timeout"):
        client.get_courses()


@pytest.mark.parametrize(
    "response",
    [
        _response(text="", url=COURSE_LIST_URL),
        _response(text="Bad gateway", url=COURSE_LIST_URL, status=502),
        _response({"result": False, "errorMsg": "操作频繁"}, url=COURSE_LIST_URL),
    ],
)
def test_bad_course_response_is_not_an_empty_course_list(monkeypatch, response):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response(text='<ul class="file-list"></ul>')))
    monkeypatch.setattr(client.session, "post", Mock(return_value=response))

    with pytest.raises(requests.RequestException):
        client.get_courses()


def test_course_auth_redirect_is_not_a_successful_empty_list(monkeypatch):
    client = ChaoxingSigninClient()
    redirected = _response(text="<html>Login</html>", url="https://passport2.chaoxing.com/login")
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response(text='<ul class="file-list"></ul>')))
    monkeypatch.setattr(client.session, "post", Mock(return_value=redirected))

    with pytest.raises(SigninSessionExpiredError):
        client.get_courses()


@pytest.mark.parametrize("stage", ["interaction", "courses"])
@pytest.mark.parametrize(
    "page,exception",
    [
        ("<html><body>访问过于频繁，请稍后重试</body></html>", requests.RequestException),
        ('<script>top.location.href="https://passport2.chaoxing.com/login";</script>', SigninSessionExpiredError),
        ('<script>window.location.replace("https://passport2.chaoxing.com/login");</script>', SigninSessionExpiredError),
        ("<html><body>Unknown upstream page</body></html>", requests.RequestException),
    ],
)
def test_error_html_cannot_be_reported_as_no_courses_or_signin(monkeypatch, stage, page, exception):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(
        client.session,
        "get",
        Mock(return_value=_response(text=page if stage == "interaction" else '<ul class="file-list"></ul>')),
    )
    monkeypatch.setattr(client.session, "post", Mock(return_value=_response(text=page)))

    with pytest.raises(exception):
        client.get_courses()
    with pytest.raises(exception):
        client.get_active_tasks()


def test_explicit_empty_course_page_remains_a_successful_empty_scan(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(
        client.session, "get", Mock(return_value=_response(text='<ul class="file-list"></ul><span>全部课程</span>'))
    )
    monkeypatch.setattr(
        client.session, "post", Mock(return_value=_response(text='<div class="null-data">暂无课程</div><a>全部课程</a>'))
    )

    assert client.get_courses() == []
    assert client.get_active_tasks() == []


def test_hidden_course_fields_stay_inside_each_card():
    client = ChaoxingSigninClient()
    content = """
    <div class="wrapper">
      <input value="101" name="courseId"><input value="102" name="clazzId">
      <a href="/studentcourse?courseid=101&amp;clazzid=102&amp;cpi=103"></a>
      <span class="course-name">First Course</span>
    </div>
    <div class="wrapper">
      <input value="201" name="courseId"><input value="202" name="clazzId">
      <span class="course-name">Second Course</span>
    </div>
    """

    courses = client._parse_courses(content)

    assert [(item["courseId"], item["classId"], item["cpi"], item["courseName"]) for item in courses] == [
        ("101", "102", "103", "First Course"),
        ("201", "202", "", "Second Course"),
    ]


def test_href_courses_keep_cpi_inside_their_own_link():
    client = ChaoxingSigninClient()
    courses = client._parse_courses(
        '<a href="/p?courseid=101&amp;clazzid=102&amp;cpi=103">First</a>'
        '<a href="/p?courseid=201&amp;clazzid=202">Second</a>'
    )

    assert [course["id"] for course in courses] == ["101_102_103", "201_202"]


def test_structured_course_without_cpi_does_not_borrow_neighbour_cpi():
    client = ChaoxingSigninClient()
    courses = client._parse_courses(
        '<div class="course" id="course_101_102"><span class="course-name">First</span></div>'
        '<div class="course" id="course_201_202"><a href="/p?cpi=203" title="Second"></a></div>'
    )

    assert [(item["id"], item["courseName"]) for item in courses] == [("101_102", "First"), ("201_202_203", "Second")]


def test_detection_uses_the_full_course_and_activity_protocol(monkeypatch):
    client = ChaoxingSigninClient()
    activity = {"id": "301", "otherId": "0", "status": "1", "startTime": 1, "nameOne": "签到"}
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == INTERACTION_URL:
            return _response(text='<ul><li fileid="10"></li></ul>', url=url)
        if url == ACTIVE_LIST_URL:
            return _response({"result": True, "data": {"activeList": [activity]}}, url=url)
        assert url == PPT_ACTIVE_INFO_URL
        return _response({"result": True, "data": {"ifphoto": 1}}, url=url)

    def post(url, **kwargs):
        assert url == COURSE_LIST_URL
        data = kwargs["data"]
        assert data["courseFolderSize"] == 0
        if data["courseFolderId"] == "0":
            return _response(text="<div>暂无课程</div>", url=url)
        assert data["courseFolderId"] == "10"
        return _response(text='<div id="course_100_200"><a title="Folder course"></a></div>', url=url)

    monkeypatch.setattr(client.session, "get", get)
    monkeypatch.setattr(client.session, "post", post)

    tasks = client.get_active_tasks(expected_type="photo")

    assert [(task["activeId"], task["rawCourseId"], task["classId"], task["type"]) for task in tasks] == [
        ("301", "100", "200", "photo")
    ]
    assert tasks[0]["courseName"] == "Folder course"
    assert [url for url, _ in calls] == [INTERACTION_URL, ACTIVE_LIST_URL, PPT_ACTIVE_INFO_URL]


def test_non_signin_and_bad_numeric_fields_do_not_hide_valid_signin(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client, "get_courses", lambda: [{"courseId": "100", "classId": "200"}])
    monkeypatch.setattr(
        client,
        "_get_course_activity_list",
        lambda *args: [
            {"id": "quiz", "status": 1, "otherId": 17},
            {"id": "unknown", "status": 1},
            {"id": "bad", "status": "invalid", "otherId": "invalid"},
            {"id": "ended", "status": 2, "otherId": 4},
            {"activeId": "301", "status": "1", "otherId": "4", "endTime": "invalid"},
        ],
    )

    tasks = client.get_active_tasks()

    assert [task["activeId"] for task in tasks] == ["301"]
    assert tasks[0]["deadline"] is None


def test_partial_failure_without_results_cannot_report_no_signin(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(
        client, "get_courses", lambda: [{"courseId": "1", "classId": "2"}, {"courseId": "3", "classId": "4"}]
    )
    monkeypatch.setattr(client, "_get_course_activity_list", Mock(side_effect=[requests.Timeout("retry later"), []]))

    with pytest.raises(requests.RequestException, match="1/2.*retry later"):
        client.get_active_tasks()


def test_one_failed_course_does_not_hide_another_courses_signin(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(
        client, "get_courses", lambda: [{"courseId": "1", "classId": "2"}, {"courseId": "3", "classId": "4"}]
    )
    monkeypatch.setattr(
        client,
        "_get_course_activity_list",
        Mock(side_effect=[requests.Timeout("retry later"), [{"id": "5", "status": 1, "otherId": 4}]]),
    )

    assert [task["activeId"] for task in client.get_active_tasks()] == ["5"]


def test_class_activity_does_not_request_signin_details_for_a_quiz(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client, "get_courses", lambda: [{"courseId": "1", "classId": "2"}])
    monkeypatch.setattr(client, "_get_course_activity_list", lambda *args: [{"id": "quiz", "status": 1, "otherId": 17}])
    detail = Mock(side_effect=AssertionError("a quiz is not a PPT sign-in"))
    monkeypatch.setattr(client, "get_ppt_active_info", detail)

    activities = client.get_class_activities("2")

    assert activities[0]["type"] == "unknown"
    detail.assert_not_called()


def test_class_activity_failure_is_not_an_empty_class(monkeypatch):
    client = ChaoxingSigninClient()
    monkeypatch.setattr(client, "get_courses", lambda: [{"courseId": "1", "classId": "2"}])
    monkeypatch.setattr(client, "_get_course_activity_list", Mock(side_effect=requests.Timeout("retry later")))

    with pytest.raises(requests.Timeout):
        client.get_class_activities("2")


@pytest.mark.parametrize("method,args", [("get_courses", ()), ("get_classes", ()), ("get_class_activities", ("2",))])
def test_manager_requires_platform_login(manager, method, args):
    with pytest.raises(SigninSessionExpiredError, match="先登录学习通"):
        getattr(manager, method)("user-1", *args)


def test_manager_requires_platform_login_for_empty_live_feed(manager):
    with pytest.raises(SigninSessionExpiredError):
        manager.get_active_tasks("user-1")


def test_live_discovery_error_is_not_replaced_by_background_feed(manager):
    manager._clients["user-1"] = Mock()
    manager._clients["user-1"].get_active_tasks.side_effect = SigninSessionExpiredError("学习通登录已失效")
    manager._build_background_task_feed = Mock(return_value=[{"source": "background"}])

    with pytest.raises(SigninSessionExpiredError):
        manager.get_active_tasks("user-1")
    manager._build_background_task_feed.assert_not_called()


def test_presign_runs_upstream_analysis_chain_before_submit(monkeypatch):
    client = ChaoxingSigninClient()
    task = {"rawCourseId": "1", "classId": "2", "activeId": "3", "type": "normal"}
    events = []

    def get(url, **kwargs):
        events.append(url)
        if url == SIGN_ANALYSIS_URL:
            assert kwargs["params"] == {"vs": 1, "DB_STRATEGY": "RANDOM", "aid": "3"}
            return _response(text="location.href='/pptSign/analysis2?DB_STRATEGY=RANDOM&code='+'abc123';", url=url)
        if url == SIGN_ANALYSIS2_URL:
            assert kwargs["params"] == {"DB_STRATEGY": "RANDOM", "code": "abc123"}
        else:
            assert url == PRE_SIGN_URL
            assert kwargs["params"]["activePrimaryId"] == "3"
        return _response(text="ok", url=url)

    def submit(_task):
        events.append("submit")
        return "success"

    monkeypatch.setattr(client.session, "get", get)
    monkeypatch.setattr(signin_module.time, "sleep", lambda seconds: events.append(seconds))
    monkeypatch.setattr(client, "_sign_general", submit)

    assert client.sign_task(task)["status"] is True
    assert events == [PRE_SIGN_URL, SIGN_ANALYSIS_URL, SIGN_ANALYSIS2_URL, 0.5, "submit"]


def test_failed_presign_does_not_submit_or_abort_the_batch(monkeypatch):
    client = ChaoxingSigninClient()
    task = {"rawCourseId": "1", "classId": "2", "activeId": "3", "type": "normal"}
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response(text="invalid analysis")))
    submit = Mock()
    monkeypatch.setattr(client, "_sign_general", submit)

    result = client.sign_task(task)

    assert result["status"] is False
    assert "校验未返回有效凭证" in result["message"]
    submit.assert_not_called()


def test_background_worker_records_discovery_failure(manager, monkeypatch):
    client = Mock()
    client.get_active_tasks.side_effect = requests.RequestException("activelist returned no activity list")
    manager._clients["user-1"] = client
    monkeypatch.setattr(manager, "login", lambda *args: {"status": True})
    updates = []
    monkeypatch.setattr(manager, "_update_task", lambda task_id, **changes: updates.append(changes))
    monkeypatch.setattr(manager, "_append_task_log", Mock())

    manager._run_task_worker("task-1", "user-1", {"username": "demo", "password": "demo"})

    assert updates[-1]["status"] == "error"
    assert "activelist returned no activity list" in updates[-1]["message"]
    client.sign_task.assert_not_called()
