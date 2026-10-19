"""Group-chat protocol regressions. All requests are mocked; nothing is sent."""

import json
from unittest.mock import Mock

import pytest
import requests

import app.services.course.chaoxing.signin as signin_module
from app.services.course.chaoxing.chat_signin import (
    CHAT_PRE_SIGN_URL,
    CHAT_SIGN_URL,
    IM_CHANNELS_BASE_URL,
    IM_TOKEN_URL,
    LOGIN_USER_URL,
    ChaoxingChatSigninService,
    parse_chat_target,
)
from app.services.course.chaoxing.signin import ChaoxingSigninClient, ChaoxingSigninManager, SigninSessionExpiredError


def _response(payload=None, *, text=None, status=200, url=LOGIN_USER_URL):
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.encoding = "utf-8"
    response._content = (json.dumps(payload) if text is None else text).encode()
    return response


@pytest.fixture
def client():
    client = ChaoxingSigninClient()
    client.session.cookies.set("_uid", "100")
    return client


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(signin_module.task_store, "list_tasks", lambda *args, **kwargs: [])
    monkeypatch.setattr(signin_module.task_store, "list_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(signin_module.task_store, "append_history", lambda *args, **kwargs: None)
    return ChaoxingSigninManager()


def _channel(chat_id="200", active_id="300", **card_values):
    card = {"aid": active_id, "atype": 2, "atypeName": "普通签到", "title": "测试签到", **card_values}
    payload = {"ext": {"attachment": {"att_chat_course": card}}}
    return {
        "session_type": "groupchat",
        "session_to": chat_id,
        "channel_id": f"{chat_id}@conference.easemob.com",
        "meta": {"payload": json.dumps(payload), "timestamp": 123456789},
    }


def _mock_requests(monkeypatch, client, *, channels=None, page=None, submit="success"):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == LOGIN_USER_URL:
            return _response({"result": 1, "msg": {"puid": "100", "name": "Tester"}}, url=url)
        if url == IM_TOKEN_URL:
            return _response({"result": 1, "data": {"hxToken": "private-token", "uid": "im100"}}, url=url)
        if url.startswith(IM_CHANNELS_BASE_URL):
            return _response({"data": {"channel_infos": channels or []}}, url=url)
        if url == CHAT_PRE_SIGN_URL:
            return _response(
                text=page if page is not None else '<div>普通签到</div><script>$.get("stuSignajax")</script>', url=url
            )
        assert url == CHAT_SIGN_URL
        return _response(text=submit, url=url)

    def post(url, **kwargs):
        # Only the location sign-in form is POSTed; messages are never sent.
        assert url == CHAT_SIGN_URL
        calls.append((url, kwargs))
        return _response(text=submit, url=url)

    monkeypatch.setattr(client.session, "get", get)
    monkeypatch.setattr(client.session, "post", post)
    return calls


# Shape of the real location preStuSign page: it never says 「位置签到」.
LOCATION_PAGE = """<div class="zgetSite"><div class="zgetSite_box" id="maptishi"><div id="dituContent"></div></div>
<input type="hidden" id="latitude" value="-1"><input type="hidden" id="longitude" value="-1">
<input type="hidden" id="paramAddress" value="">
<div class="zgetSite_agree" id="itj"><input type="checkbox" name="ifTiJiao" id="ifTiJiao" checked="checked"/>
<label for="ifTiJiao">同意提交位置信息</label></div><p class="zre_go"><a href="javascript:sign();">签到</a></p></div>
<script src="https://mobilelearn-static.chaoxing.com/mobilelearn/js/widget/client-user-location-address.js"></script>
<script>var url="/sign/stuSignajax";</script>"""


@pytest.mark.parametrize(
    "chat,active,url",
    [
        ("200", "300", None),
        (None, None, "https://mobilelearn.chaoxing.com/sign/preStuSign?chatId=200&activeId=300"),
        ("200", None, "https://mobilelearn.chaoxing.com/sign/preStuSign?aid=300"),
        (None, None, "https://mobilelearn.chaoxing.com/sign/preStuSign?chatid=200&amp;activePrimaryId=300"),
    ],
)
def test_target_accepts_explicit_ids_or_chaoxing_link(chat, active, url):
    assert parse_chat_target(chat, active, url) == ("200", "300")


@pytest.mark.parametrize(
    "chat,active,url",
    [
        (None, "300", None),
        ("200", None, None),
        ("../200", "300", None),
        ("200", "3&uid=999", None),
        ("0", "300", None),
        ("9" * 33, "300", None),
        (None, None, "https://example.com/sign?chatId=200&activeId=300"),
        (None, None, "https://mobilelearn.chaoxing.com@evil.test/sign?chatId=200&activeId=300"),
        (None, None, "https://mobilelearn.chaoxing.com:443/sign?chatId=200&activeId=300"),
        (None, None, "https://mobilelearn.chaoxing.com/sign?chatId=200&activeId=300&activeId=301"),
        ("201", "300", "https://mobilelearn.chaoxing.com/sign?chatId=200&activeId=300"),
    ],
)
def test_target_rejects_unsafe_missing_and_conflicting_values(chat, active, url):
    with pytest.raises(ValueError):
        parse_chat_target(chat, active, url)


def test_latest_json_card_discovery_is_read_only_and_keeps_ids(client, monkeypatch):
    calls = _mock_requests(monkeypatch, client, channels=[_channel()])

    result = ChaoxingChatSigninService(client).get_tasks()

    assert result["scope"] == "latest_messages"
    assert len(result["warnings"]) == 1
    task = result["tasks"][0]
    assert (task["subjectType"], task["chatId"], task["activeId"], task["type"], task["actionable"]) == (
        "chat", "200", "300", "normal", True
    )
    assert "token" not in json.dumps(result)
    assert [url for url, _ in calls] == [
        LOGIN_USER_URL, IM_TOKEN_URL, f"{IM_CHANNELS_BASE_URL}/im100/user_channels/list"
    ]
    assert calls[-1][1]["headers"]["Authorization"] == "Bearer private-token"
    assert calls[-1][1]["params"]["needEmptySession"] == "true"
    assert CHAT_SIGN_URL not in [url for url, _ in calls]


def test_discovery_filters_course_cards_private_messages_and_other_chats(client, monkeypatch):
    private = _channel()
    private["session_type"] = "chat"
    private["channel_id"] = "200@easemob.com"
    _mock_requests(
        monkeypatch, client,
        channels=[private, _channel(courseInfo={"courseid": "999"}), _channel("201"), _channel()],
    )

    tasks = ChaoxingChatSigninService(client).get_tasks(chat_id="200")["tasks"]

    assert len(tasks) == 1
    assert tasks[0]["chatId"] == "200"


def test_location_card_is_actionable_and_other_types_are_not(client, monkeypatch):
    _mock_requests(
        monkeypatch, client, channels=[_channel("200", atypeName="位置签到"), _channel("201", atypeName="拍照签到")]
    )

    location, photo = ChaoxingChatSigninService(client).get_tasks()["tasks"]

    assert (location["type"], location["actionable"]) == ("location", True)
    assert "unsupportedReason" not in location
    assert (photo["type"], photo["actionable"]) == ("photo", False)
    assert "普通签到和位置签到" in photo["unsupportedReason"]


def test_base64_latest_message_is_explicitly_unsupported(client, monkeypatch):
    channel = _channel()
    channel["meta"]["payload"] = "YWJjZA=="
    _mock_requests(monkeypatch, client, channels=[channel])

    result = ChaoxingChatSigninService(client).get_tasks()

    assert result["tasks"] == []
    assert any("Base64/protobuf" in message for message in result["warnings"])


def test_empty_group_list_has_scope_warning(client, monkeypatch):
    _mock_requests(monkeypatch, client, channels=[])
    result = ChaoxingChatSigninService(client).get_tasks()
    assert result["tasks"] == []
    assert "最新一条" in result["warnings"][0]


def test_discovery_does_not_guess_malformed_activity_ids(client, monkeypatch):
    _mock_requests(monkeypatch, client, channels=[_channel(active_id="invalid")])
    result = ChaoxingChatSigninService(client).get_tasks()
    assert result["tasks"] == []
    assert len(result["warnings"]) == 2


@pytest.mark.parametrize("status,exception", [(401, SigninSessionExpiredError), (502, requests.HTTPError)])
def test_group_credential_http_errors_remain_distinct(client, monkeypatch, status, exception):
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response(text="error", status=status)))
    with pytest.raises(exception):
        ChaoxingChatSigninService(client).get_tasks()


def test_expired_group_credentials_use_platform_session_error(client, monkeypatch):
    monkeypatch.setattr(
        client.session, "get", Mock(return_value=_response({"result": 0, "msg": "请先登录"}))
    )
    with pytest.raises(SigninSessionExpiredError):
        ChaoxingChatSigninService(client).get_tasks()


def test_group_user_cannot_differ_from_current_session(client, monkeypatch):
    monkeypatch.setattr(client.session, "get", Mock(return_value=_response({"result": 1, "msg": {"puid": "999"}})))
    with pytest.raises(SigninSessionExpiredError, match="账号不一致"):
        ChaoxingChatSigninService(client).get_tasks()


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {"channels": None}}, {"data": {"channels": [None]}}])
def test_bad_channel_envelope_is_an_upstream_error(client, monkeypatch, payload):
    _mock_requests(monkeypatch, client)
    original_get = client.session.get

    def get(url, **kwargs):
        if url.startswith(IM_CHANNELS_BASE_URL):
            return _response(payload, url=url)
        return original_get(url, **kwargs)

    monkeypatch.setattr(client.session, "get", get)
    with pytest.raises(requests.RequestException, match="channels"):
        ChaoxingChatSigninService(client).get_tasks()


def test_malformed_token_cannot_be_used_as_an_auth_header(client, monkeypatch):
    _mock_requests(monkeypatch, client)
    original_get = client.session.get

    def get(url, **kwargs):
        if url == IM_TOKEN_URL:
            return _response({"result": 1, "data": {"hxToken": "bad\r\nheader", "uid": "im100"}}, url=url)
        return original_get(url, **kwargs)

    monkeypatch.setattr(client.session, "get", get)
    with pytest.raises(requests.RequestException, match="凭证格式异常"):
        ChaoxingChatSigninService(client).get_tasks()


def test_pagination_limit_is_disclosed(client, monkeypatch):
    _mock_requests(monkeypatch, client, channels=[_channel(str(200 + index)) for index in range(51)])
    result = ChaoxingChatSigninService(client).get_tasks()
    assert len(result["tasks"]) == 50
    assert any("50" in message for message in result["warnings"])


def test_normal_group_signin_uses_group_protocol_and_current_identity(client, monkeypatch):
    calls = _mock_requests(monkeypatch, client)

    result = ChaoxingChatSigninService(client).sign_once(
        activity_url="https://mobilelearn.chaoxing.com/sign/preStuSign?activeId=300&chatId=200&uid=999"
    )

    assert result["status"] is True
    assert result["data"]["task"]["taskId"] == "chat:200:300"
    assert [url for url, _ in calls] == [LOGIN_USER_URL, IM_TOKEN_URL, CHAT_PRE_SIGN_URL, CHAT_SIGN_URL]
    assert calls[-2][1]["params"] == {
        "activeId": "300", "code": "", "uid": "100", "courseId": "null", "classId": 0,
        "general": 0, "chatId": "200", "appType": 0, "tid": "im100", "atype": "null", "sys": 0,
    }
    assert calls[-1][1]["params"] == {"activeId": "300", "uid": "100", "clientip": ""}


@pytest.mark.parametrize(
    "page",
    [
        "<div>请拍照签到</div>",
        "<div>请拍照签到</div>",
        "<div>二维码签到</div>",
        '<input name="otherId" value="3"><div>签到</div>',
        '<input name="otherId" value="0"><input name="ifphoto" value="1">',
        '<input name="otherId" value="17"><div>签到</div><script>stuSignajax</script>',
        "<div>签到已结束</div>",
        "<div>未知页面</div>",
    ],
)
def test_unsupported_or_unconfirmed_activity_never_submits(client, monkeypatch, page):
    calls = _mock_requests(monkeypatch, client, page=page)
    result = ChaoxingChatSigninService(client).sign_once("200", "300")
    assert result["status"] is False
    assert CHAT_SIGN_URL not in [url for url, _ in calls]


@pytest.mark.parametrize(
    "location",
    [None, {}, {"latitude": None, "longitude": None}, {"latitude": -1, "longitude": -1}, {"latitude": "x", "longitude": 1}],
)
def test_location_signin_without_coordinates_is_refused_before_submitting(client, monkeypatch, location):
    calls = _mock_requests(monkeypatch, client, page=LOCATION_PAGE)

    result = ChaoxingChatSigninService(client).sign_once("200", "300", location=location)

    assert result["status"] is False
    assert result["data"]["requiresLocation"] is True
    assert result["data"]["task"]["type"] == "location"
    assert CHAT_SIGN_URL not in [url for url, _ in calls]


@pytest.mark.parametrize("page", [LOCATION_PAGE, "<div>位置签到</div><script>stuSignajax</script>"])
def test_location_signin_posts_the_group_location_form(client, monkeypatch, page):
    calls = _mock_requests(monkeypatch, client, page=page)

    result = ChaoxingChatSigninService(client).sign_once(
        "200", "300", location={"latitude": 39.9087, "longitude": 116.3975, "address": "天安门"}
    )

    assert result["status"] is True
    assert result["data"]["task"]["type"] == "location"
    assert calls[-1][0] == CHAT_SIGN_URL
    assert calls[-1][1]["data"] == {
        "address": "天安门",
        "latitude": "39.9087",
        "longitude": "116.3975",
        "activeId": "300",
        "uid": "100",
        "clientip": "",
        "useragent": "",
        "fid": "",
        "ifTiJiao": 1,
    }


def test_explicit_normal_type_is_not_overridden_by_location_markers(client, monkeypatch):
    calls = _mock_requests(monkeypatch, client, page='<input name="otherId" value="0">' + LOCATION_PAGE)

    result = ChaoxingChatSigninService(client).sign_once("200", "300")

    assert result["status"] is True
    assert calls[-1][1]["params"] == {"activeId": "300", "uid": "100", "clientip": ""}


@pytest.mark.parametrize("submit", ["fail", "successfully", "SUCCESS", "fail-need-qrcode"])
def test_only_exact_success_is_success(client, monkeypatch, submit):
    _mock_requests(monkeypatch, client, submit=submit)
    assert ChaoxingChatSigninService(client).sign_once("200", "300")["status"] is False


def test_signin_timeout_propagates_as_upstream_failure(client, monkeypatch):
    calls = _mock_requests(monkeypatch, client)
    original_get = client.session.get

    def get(url, **kwargs):
        if url == CHAT_SIGN_URL:
            raise requests.Timeout("submit timeout")
        return original_get(url, **kwargs)

    monkeypatch.setattr(client.session, "get", get)
    with pytest.raises(requests.Timeout):
        ChaoxingChatSigninService(client).sign_once("200", "300")
    assert CHAT_PRE_SIGN_URL in [url for url, _ in calls]


@pytest.mark.parametrize("stage", [CHAT_PRE_SIGN_URL, CHAT_SIGN_URL])
@pytest.mark.parametrize("status,exception", [(401, SigninSessionExpiredError), (502, requests.HTTPError)])
def test_presign_and_submit_http_errors_keep_platform_or_upstream_type(client, monkeypatch, stage, status, exception):
    calls = _mock_requests(monkeypatch, client)
    original_get = client.session.get

    def get(url, **kwargs):
        if url == stage:
            return _response(text="upstream error", status=status, url=url)
        return original_get(url, **kwargs)

    monkeypatch.setattr(client.session, "get", get)
    with pytest.raises(exception):
        ChaoxingChatSigninService(client).sign_once("200", "300")
    if stage == CHAT_PRE_SIGN_URL:
        assert CHAT_SIGN_URL not in [url for url, _ in calls]


def test_rate_limited_presign_is_a_detection_error(client, monkeypatch):
    calls = _mock_requests(monkeypatch, client, page="<div>访问过于频繁，请稍后重试</div>")
    with pytest.raises(requests.RequestException, match="请求受限"):
        ChaoxingChatSigninService(client).sign_once("200", "300")
    assert CHAT_SIGN_URL not in [url for url, _ in calls]


def test_manager_group_discovery_requires_platform_login(manager):
    with pytest.raises(SigninSessionExpiredError):
        manager.get_chat_tasks("u1")


def test_manager_validates_target_before_logging_in(manager, monkeypatch):
    login = Mock()
    monkeypatch.setattr(manager, "login", login)
    with pytest.raises(ValueError):
        manager.sign_chat_once("u1", "demo", "secret", chat_id="bad", active_id="300")
    login.assert_not_called()


def test_manager_group_signin_records_history_without_course_discovery(manager, client, monkeypatch):
    _mock_requests(monkeypatch, client)
    monkeypatch.setattr(manager, "login", lambda *args: {"status": True})
    manager._clients["u1"] = client
    monkeypatch.setattr(client, "get_courses", Mock(side_effect=AssertionError("group needs no courses")))

    result = manager.sign_chat_once("u1", "demo", "secret", chat_id="200", active_id="300")

    assert result["status"] is True
    history = manager.get_history("u1")
    assert len(history) == 1
    assert (history[0]["subjectType"], history[0]["chatId"], history[0]["activeId"], history[0]["status"]) == (
        "chat", "200", "300", "success"
    )
    assert "secret" not in json.dumps(history)
    assert "private-token" not in json.dumps(history)


def test_manager_group_network_failure_records_failure_and_reraises(manager, client, monkeypatch):
    monkeypatch.setattr(manager, "login", lambda *args: {"status": True})
    manager._clients["u1"] = client
    monkeypatch.setattr(client.session, "get", Mock(side_effect=requests.Timeout("network timeout")))

    with pytest.raises(requests.Timeout):
        manager.sign_chat_once("u1", "demo", "secret", chat_id="200", active_id="300")

    assert manager.get_history("u1")[0]["status"] == "failed"
