import base64
import io
import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.datastructures import FormData, Headers, UploadFile

import app.api.v1.chaoxing as chaoxing_api
import app.api.v1.course as course_api


class FakeZhihuishuAdapter:
    def __init__(self):
        self._progress = {
            "status": "running",
            "message": "Task is running",
            "total": 2,
            "completed": 1,
            "failed": 0,
            "percentage": 50.0,
            "current_video": "Video 1",
            "estimated_time": "6s",
            "paused": False,
        }

    def get_courses(self):
        return [{"courseId": "1001", "name": "Course A"}]

    def start_course(self, course_id: str, speed: float = 1.0, auto_answer: bool = True):
        del speed, auto_answer
        self._progress.update({"status": "running", "message": "Task started", "course_id": course_id})
        return {"task_id": "z-task-1", "status": "running", "progress": dict(self._progress)}

    def get_videos(self, course_id: str):
        return [{"id": "v1", "title": f"{course_id}-Video", "status": "learning", "progress": 50}]

    def get_progress(self, course_id: str):
        progress = dict(self._progress)
        progress["course_id"] = course_id
        return progress

    def pause_task(self):
        self._progress.update({"status": "paused", "message": "Task paused", "paused": True})
        return {"status": "paused", "message": "Task paused"}

    def resume_task(self):
        self._progress.update({"status": "running", "message": "Task resumed", "paused": False})
        return {"status": "running", "message": "Task resumed"}

    def cancel_task(self):
        self._progress.update({"status": "cancelled", "message": "Task cancelled", "paused": False})
        return {"status": "cancelled", "message": "Task cancelled"}


class FakeMultipartRequest:
    def __init__(self, form_data: FormData):
        self.headers = {"content-type": "multipart/form-data; boundary=test"}
        self._form_data = form_data

    async def form(self):
        return self._form_data

    async def json(self):
        return {}


class FakeJsonRequest:
    def __init__(self, payload):
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    async def form(self):
        return FormData([])

    async def json(self):
        return self._payload


class FakeChaoxingResponse:
    def __init__(self, text="", payload=None, status_code=200):
        self.text = text
        self._payload = payload if payload is not None else {}
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeChaoxingSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if "activelist" in url:
            return FakeChaoxingResponse(
                payload={
                    "data": {
                        "activeList": [
                            {
                                "id": 11,
                                "nameOne": "位置签到",
                                "otherId": 4,
                                "status": 1,
                            }
                        ]
                    }
                }
            )
        return FakeChaoxingResponse(
            text='<div><a href="/mooc2/resource/view?id=1" title="课程资料.pdf">下载</a></div>'
        )


class FakeChaoxingClient:
    def __init__(self):
        self.session = FakeChaoxingSession()


@pytest.fixture(autouse=True)
def reset_state():
    course_api._user_adapters.clear()
    course_api._course_tasks.clear()
    yield
    course_api._user_adapters.clear()
    course_api._course_tasks.clear()


@pytest.mark.asyncio
async def test_start_course_success():
    request = course_api.CourseStartRequest(
        platform="chaoxing",
        username="testuser",
        password="testpass",
        speed=1.5,
    )
    with patch("app.api.v1.course.signin_manager.login", return_value={"status": True, "message": "ok"}):
        response = await course_api.start_course_learning(request, current_user={"user_id": 1})

    assert response.status == "started"
    assert response.task_id


@pytest.mark.asyncio
async def test_start_course_unsupported_platform():
    request = course_api.CourseStartRequest(platform="unknown", username="u", password="p")

    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_course_learning(request, current_user={"user_id": 1})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Only chaoxing is supported"


@pytest.mark.asyncio
async def test_course_login_and_courses():
    request = course_api.CourseStartRequest(platform="chaoxing", username="u", password="p")
    mock_courses = [{"id": "1_2", "courseId": "1", "classId": "2", "name": "Course A"}]

    with patch("app.api.v1.course.signin_manager.login", return_value={"status": True, "message": "ok"}), patch(
        "app.api.v1.course.signin_manager.get_courses", return_value=mock_courses
    ):
        login_resp = await course_api.course_login(request, current_user={"user_id": 1})
        list_resp = await course_api.get_courses(current_user={"user_id": 1})

    assert login_resp["courses"] == mock_courses
    assert list_resp["courses"] == mock_courses


@pytest.mark.asyncio
async def test_chaoxing_course_portal_urls_use_real_desktop_tabs():
    mock_courses = [{"id": "1_2_3", "courseId": "1", "classId": "2", "cpi": "3", "name": "Course A"}]

    with patch("app.api.v1.course.signin_manager.get_courses", return_value=mock_courses):
        response = await course_api.chaoxing_course_portal_urls("1_2", current_user={"user_id": 1})

    tabs = {tab["key"]: tab for tab in response["tabs"]}
    assert response["course"]["id"] == "1_2_3"
    assert "pageHeader=0" in tabs["activities"]["shellUrl"]
    assert "mobilelearn.chaoxing.com/page/active/stuActiveList" in tabs["activities"]["frameUrl"]
    assert "mobilelearn.chaoxing.com/v2/apis/active/student/activelist" in tabs["activities"]["remoteRequest"]["url"]
    assert "mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist" in tabs["resources"]["frameUrl"]
    assert "mooc1.chaoxing.com/mooc2/work/list" in tabs["homework"]["frameUrl"]
    assert "proxyEndpoint" not in tabs["activities"]
    assert tabs["activities"]["directBrowserRequest"] is True


@pytest.mark.asyncio
async def test_chaoxing_course_resources_and_activities_fetch_from_real_routes():
    fake_client = FakeChaoxingClient()
    mock_courses = [{"id": "1_2_3", "courseId": "1", "classId": "2", "cpi": "3", "name": "Course A"}]

    with patch("app.api.v1.course.signin_manager.get_client", return_value=fake_client), patch(
        "app.api.v1.course.signin_manager.get_courses", return_value=mock_courses
    ):
        resources = await course_api.chaoxing_course_resources("1_2", current_user={"user_id": 1})
        activities = await course_api.chaoxing_course_activities("1_2_3", current_user={"user_id": 1})

    assert resources["resources"][0]["title"] == "课程资料.pdf"
    assert resources["resources"][0]["url"].startswith("https://mooc2-ans.chaoxing.com/mooc2/resource/view")
    assert activities["activities"][0]["type"] == "location"
    assert any("stu-datalist" in call["url"] for call in fake_client.session.calls)
    assert any("activelist" in call["url"] for call in fake_client.session.calls)


@pytest.mark.asyncio
async def test_chaoxing_compat_login_and_courses():
    mock_courses = [{"id": "1_2", "courseId": "1", "classId": "2", "name": "Course A"}]
    login_request = chaoxing_api.ChaoxingLoginRequest(username="u", password="p", use_cookies=False)

    with patch("app.api.v1.chaoxing.signin_manager.login", return_value={"status": True, "message": "ok", "data": {}}), patch(
        "app.api.v1.chaoxing.signin_manager.get_courses", return_value=mock_courses
    ):
        login_resp = await chaoxing_api.chaoxing_login(login_request, user_id="1")
        courses_resp = await chaoxing_api.chaoxing_courses(user_id="1")

    assert login_resp["status"] is True
    assert courses_resp["data"] == mock_courses


@pytest.mark.asyncio
async def test_chaoxing_class_subject_routes_are_parallel_to_courses():
    mock_classes = [
        {
            "id": "1_2",
            "subjectType": "class",
            "subjectId": "2",
            "classId": "2",
            "courseId": "1",
            "name": "Class A",
        }
    ]
    mock_activities = [{"activeId": "11", "classId": "2", "type": "location"}]

    with patch("app.api.v1.chaoxing.signin_manager.get_classes", return_value=mock_classes), patch(
        "app.api.v1.chaoxing.signin_manager.get_class_activities", return_value=mock_activities
    ) as mock_get_activities:
        classes_resp = await chaoxing_api.chaoxing_classes(user_id="1")
        activities_resp = await chaoxing_api.chaoxing_class_activities(
            "2",
            course_id="1",
            user_id="1",
        )

    assert classes_resp["classes"] == mock_classes
    assert activities_resp["activities"] == mock_activities
    assert mock_get_activities.call_args.kwargs["class_id"] == "2"
    assert mock_get_activities.call_args.kwargs["course_id"] == "1"


@pytest.mark.asyncio
async def test_chaoxing_class_sign_passes_class_and_active_filters():
    with patch(
        "app.api.v1.chaoxing.signin_manager.sign_class_once",
        return_value={"status": True, "message": "ok", "data": {"task": {"classId": "2"}}},
    ) as mock_sign:
        response = await chaoxing_api.chaoxing_class_sign(
            raw_request=FakeJsonRequest(
                {
                    "username": "u",
                    "password": "p",
                    "sign_type": "location",
                    "classId": "2",
                    "courseId": "1_2",
                    "activeId": "11",
                }
            ),
            user_id="1",
        )

    assert response["status"] is True
    assert mock_sign.call_args.kwargs["class_id"] == "2"
    assert mock_sign.call_args.kwargs["course_id"] == "1_2"
    assert mock_sign.call_args.kwargs["active_id"] == "11"
    assert mock_sign.call_args.kwargs["sign_type"] == "location"


@pytest.mark.asyncio
async def test_chaoxing_class_start_uses_class_task_manager():
    captured = {}

    def _fake_start_class_task(user_id, payload):
        captured["user_id"] = user_id
        captured["payload"] = payload
        return "class-task-1"

    with patch("app.api.v1.chaoxing.signin_manager.start_class_task", side_effect=_fake_start_class_task):
        response = await chaoxing_api.chaoxing_class_start(
            raw_request=FakeJsonRequest(
                {
                    "username": "u",
                    "password": "p",
                    "classList": ["2"],
                    "courseList": ["1_2"],
                    "sign_type": "all",
                }
            ),
            user_id="1",
        )

    assert response["status"] is True
    assert response["data"]["task_id"] == "class-task-1"
    assert captured["user_id"] == "1"
    assert captured["payload"]["class_list"] == ["2"]
    assert captured["payload"]["course_list"] == ["1_2"]
    assert captured["payload"]["subject_type"] == "class"


@pytest.mark.asyncio
async def test_chaoxing_signin_remote_endpoints_are_remote_urls():
    with patch(
        "app.api.v1.chaoxing.signin_manager.get_remote_endpoints",
        return_value={
            "directBrowserRequest": True,
            "endpoints": {
                "submitSign": {
                    "url": "https://mobilelearn.chaoxing.com/pptSign/stuSignajax?activeId=11",
                }
            },
        },
    ) as mock_get_remote:
        response = await chaoxing_api.chaoxing_remote_endpoints(
            course_id="1_2",
            class_id="2",
            active_id="11",
            user_id="1",
        )

    assert response["remoteEndpoints"]["directBrowserRequest"] is True
    assert response["remoteEndpoints"]["endpoints"]["submitSign"]["url"].startswith("https://mobilelearn.chaoxing.com")
    assert mock_get_remote.call_args.kwargs["course_id"] == "1_2"
    assert mock_get_remote.call_args.kwargs["class_id"] == "2"
    assert mock_get_remote.call_args.kwargs["active_id"] == "11"


@pytest.mark.asyncio
async def test_zhihuishu_required_endpoints():
    user_id = "1"
    adapter = FakeZhihuishuAdapter()
    course_api._user_adapters[user_id] = {"adapter": adapter, "last_access": time.time()}

    courses_resp = await course_api.zhihuishu_get_courses(current_user={"user_id": 1})
    start_resp = await course_api.zhihuishu_start_course(
        course_api.ZhihuishuCourseRequest(course_id="1001", speed=1.0, auto_answer=True),
        current_user={"user_id": 1},
    )
    videos_resp = await course_api.zhihuishu_get_videos("1001", current_user={"user_id": 1})
    progress_resp = await course_api.zhihuishu_get_progress("1001", current_user={"user_id": 1})
    pause_resp = await course_api.zhihuishu_pause(current_user={"user_id": 1})
    resume_resp = await course_api.zhihuishu_resume(current_user={"user_id": 1})
    cancel_resp = await course_api.zhihuishu_cancel(current_user={"user_id": 1})

    assert isinstance(courses_resp.get("courses"), list)
    assert start_resp.get("task_id")
    assert isinstance(videos_resp.get("videos"), list)
    assert "completed" in progress_resp
    assert "total" in progress_resp
    assert pause_resp["status"] == "success"
    assert resume_resp["status"] == "success"
    assert cancel_resp["status"] == "success"


@pytest.mark.asyncio
async def test_zhihuishu_progress_does_not_overwrite_other_same_course_tasks():
    user_id = "1"
    adapter = FakeZhihuishuAdapter()
    adapter._progress.update(
        {
            "status": "completed",
            "message": "Task completed",
            "total": 2,
            "completed": 2,
            "failed": 0,
            "percentage": 100.0,
        }
    )
    course_api._user_adapters[user_id] = {"adapter": adapter, "last_access": time.time()}

    course_api._set_course_task(
        "old-task",
        {
            "task_id": "old-task",
            "platform": "zhihuishu",
            "task_type": "course",
            "course_id": "1001",
            "user_id": user_id,
            "status": "running",
            "message": "Old task still running",
            "progress": {"status": "running", "completed": 1, "total": 3},
            "current_task": "Video 2",
            "created_at": 1,
            "updated_at": 1,
        },
    )
    course_api._set_course_task(
        "active-task",
        {
            "task_id": "active-task",
            "platform": "zhihuishu",
            "task_type": "course",
            "course_id": "1001",
            "user_id": user_id,
            "status": "running",
            "message": "Active task running",
            "progress": {"status": "running", "completed": 1, "total": 2},
            "current_task": "Video 1",
            "created_at": 2,
            "updated_at": 2,
        },
    )

    progress_resp = await course_api.zhihuishu_get_progress("1001", current_user={"user_id": 1})

    assert progress_resp["status"] == "completed"
    assert course_api._course_tasks["old-task"]["status"] == "running"
    assert course_api._course_tasks["active-task"]["status"] == "running"


@pytest.mark.asyncio
async def test_chaoxing_start_accepts_multipart_photo():
    captured = {}

    def _fake_start_task(user_id, payload):
        captured["user_id"] = user_id
        captured["payload"] = payload
        return "task-multipart-1"

    form_data = FormData(
        [
            ("username", "u"),
            ("password", "p"),
            ("course_list", '["course_1"]'),
            ("sign_type", "photo"),
            ("speed", "1.0"),
            ("jobs", "1"),
            (
                "photo",
                UploadFile(
                    filename="demo.jpg",
                    file=io.BytesIO(b"fake-image"),
                    headers=Headers({"content-type": "image/jpeg"}),
                ),
            ),
        ]
    )

    with patch("app.api.v1.chaoxing.signin_manager.start_task", side_effect=_fake_start_task):
        response = await chaoxing_api.chaoxing_start(
            raw_request=FakeMultipartRequest(form_data),
            user_id="1",
        )

    assert response["status"] is True
    assert response["data"]["task_id"] == "task-multipart-1"
    assert captured["user_id"] == "1"
    assert captured["payload"]["course_list"] == ["course_1"]
    assert captured["payload"]["photo_base64"] == base64.b64encode(b"fake-image").decode("utf-8")


@pytest.mark.asyncio
async def test_notify_test_actually_sends_via_provider():
    """F32: /notify/test must really invoke a provider, not return hardcoded success."""
    sent = {}

    class FakeProvider:
        def __init__(self):
            self.disabled = False

        def send(self, message):
            sent["message"] = message
            return True

    fake = FakeProvider()

    with patch("app.api.v1.course.validate_notification_url", return_value=True), patch(
        "app.api.v1.course.NotificationFactory.create_service", return_value=fake
    ) as mock_create:
        response = await course_api.test_notification(
            {"service": "Bark", "url": "https://api.day.app/xxxx"},
            current_user={"user_id": 1},
        )

    assert mock_create.called, "NotificationFactory.create_service was never invoked"
    assert "message" in sent, "provider.send() was never called"
    assert response["status"] == "success"


@pytest.mark.asyncio
async def test_notify_test_reports_failure_when_send_raises():
    """F32: a failed delivery must NOT report success."""

    class FailingProvider:
        disabled = False

        def send(self, message):
            raise RuntimeError("connection refused")

    with patch("app.api.v1.course.validate_notification_url", return_value=True), patch(
        "app.api.v1.course.NotificationFactory.create_service",
        return_value=FailingProvider(),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await course_api.test_notification(
                {"service": "Bark", "url": "https://api.day.app/xxxx"},
                current_user={"user_id": 1},
            )

    assert exc_info.value.status_code in (502, 400)


@pytest.mark.asyncio
async def test_notify_test_rejects_internal_url():
    """F32/F55: SSRF guard must reject loopback/metadata URLs before sending."""
    with patch(
        "app.api.v1.course.NotificationFactory.create_service"
    ) as mock_create:
        with pytest.raises(HTTPException) as exc_info:
            await course_api.test_notification(
                {"service": "Bark", "url": "http://169.254.169.254/latest/meta-data/"},
                current_user={"user_id": 1},
            )

    assert exc_info.value.status_code == 400
    assert not mock_create.called, "Provider must not be created for a blocked URL"


@pytest.mark.asyncio
async def test_zhihuishu_qr_login_rejects_missing_user_id():
    """F58: str(None) == 'None' is truthy; missing user_id must be rejected."""
    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_zhihuishu_qr_login(current_user={})
    assert exc_info.value.status_code == 401
    # The 'None' string must never become a real adapter key.
    assert "None" not in course_api._user_adapters


@pytest.mark.asyncio
async def test_zhihuishu_login_status_rejects_missing_user_id():
    """F58: get_zhihuishu_login_status must reject missing user_id."""
    with pytest.raises(HTTPException) as exc_info:
        await course_api.get_zhihuishu_login_status("sess", current_user={})
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_zhihuishu_password_login_rejects_missing_user_id():
    """F58: zhihuishu_password_login must reject missing user_id."""
    request = course_api.ZhihuishuPasswordLoginRequest(username="u", password="p")
    with pytest.raises(HTTPException) as exc_info:
        await course_api.zhihuishu_password_login(request, current_user={})
    assert exc_info.value.status_code == 401
    assert "None" not in course_api._user_adapters


@pytest.mark.asyncio
async def test_geocoding_endpoints_require_auth():
    """F56: geocoding proxy endpoints must require authentication."""
    import inspect

    for fn in (
        chaoxing_api.chaoxing_location_geocode,
        chaoxing_api.chaoxing_location_search,
        chaoxing_api.chaoxing_location_reverse_geocode,
    ):
        params = inspect.signature(fn).parameters
        assert "user_id" in params, f"{fn.__name__} is missing the auth dependency"
        default = params["user_id"].default
        assert default is not inspect.Parameter.empty and hasattr(
            default, "dependency"
        ), f"{fn.__name__} user_id is not a Depends(...)"


def test_geocoding_endpoints_reject_anonymous_via_client():
    """F56 (e2e): anonymous requests to the geocoding proxy must be rejected."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, base_url="http://localhost")
    with patch("app.api.v1.chaoxing._request_photon_json") as mock_photon:
        for path in (
            "/api/v1/chaoxing/location/geocode?query=foo",
            "/api/v1/chaoxing/location/search?query=foo",
            "/api/v1/chaoxing/location/reverse-geocode?lat=1&lng=2",
        ):
            resp = client.get(path)
            assert resp.status_code == 401, f"{path} returned {resp.status_code}, expected 401"
    assert not mock_photon.called, "Photon was contacted on an unauthenticated request"


def test_geocoding_geocode_works_with_token():
    """F56 (e2e): an authenticated request still proxies normally."""
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token
    from app.main import app

    token = create_access_token({"user_id": 1, "tenant_db_name": "tenant_testuser"})
    client = TestClient(app, base_url="http://localhost")
    photon_payload = {
        "features": [
            {
                "geometry": {"coordinates": [116.4, 39.9]},
                "properties": {"name": "Somewhere", "city": "Beijing"},
            }
        ]
    }
    with patch("app.api.v1.chaoxing._request_photon_json", return_value=photon_payload):
        resp = client.get(
            "/api/v1/chaoxing/location/geocode?query=foo",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["result"]["location"] == {"lat": 39.9, "lng": 116.4}


@pytest.mark.asyncio
async def test_chaoxing_sign_accepts_multipart_photo():
    form_data = FormData(
        [
            ("username", "u"),
            ("password", "p"),
            ("sign_type", "photo"),
            (
                "photo",
                UploadFile(
                    filename="demo.jpg",
                    file=io.BytesIO(b"fake-image"),
                    headers=Headers({"content-type": "image/jpeg"}),
                ),
            ),
        ]
    )

    with patch(
        "app.api.v1.chaoxing.signin_manager.sign_once",
        return_value={"status": True, "message": "ok", "data": {}},
    ) as mock_sign_once:
        response = await chaoxing_api.chaoxing_sign(
            raw_request=FakeMultipartRequest(form_data),
            user_id="1",
        )

    assert response["status"] is True

    options = mock_sign_once.call_args.kwargs["options"]
    assert options["sign_type"] == "photo"
    assert options["photo_base64"] == base64.b64encode(b"fake-image").decode("utf-8")
