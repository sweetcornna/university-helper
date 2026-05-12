import time
from unittest.mock import Mock, patch

from app.services.course.chaoxing.signin import ChaoxingSigninClient, build_remote_sign_endpoints


def test_chaoxing_signin_client_login_success():
    client = ChaoxingSigninClient()
    client.session.cookies.set("_uid", "12345")

    mock_response = Mock()
    mock_response.json.return_value = {"status": True}

    with patch.object(client.session, "post", return_value=mock_response), patch.object(
        client, "_fetch_account_name", return_value="tester"
    ):
        result = client.login("user", "pass")

    assert result["status"] is True
    assert result["data"]["uid"] == "12345"
    assert result["data"]["name"] == "tester"


def test_chaoxing_signin_client_login_failure():
    client = ChaoxingSigninClient()

    mock_response = Mock()
    mock_response.json.return_value = {"status": False, "msg2": "invalid credentials"}

    with patch.object(client.session, "post", return_value=mock_response):
        result = client.login("user", "bad")

    assert result["status"] is False
    assert "invalid" in result["message"]


def test_chaoxing_signin_get_active_tasks_location_filter():
    client = ChaoxingSigninClient()
    now_ms = int(time.time() * 1000)

    with patch.object(
        client,
        "get_courses",
        return_value=[{"courseId": "1", "classId": "2", "courseName": "Demo Course"}],
    ), patch.object(
        client,
        "_get_course_activity_list",
        return_value=[{"id": "11", "status": 1, "otherId": 4, "nameOne": "Location Sign", "startTime": now_ms}],
    ):
        tasks = client.get_active_tasks(expected_type="location")

    assert len(tasks) == 1
    assert tasks[0]["type"] == "location"
    assert tasks[0]["courseId"] == "1_2"


def test_chaoxing_signin_get_class_subjects_are_parallel_subjects():
    client = ChaoxingSigninClient()

    with patch.object(
        client,
        "get_courses",
        return_value=[
            {
                "id": "1_2_3",
                "courseId": "1",
                "classId": "2",
                "cpi": "3",
                "courseName": "Demo Course",
            }
        ],
    ):
        subjects = client.get_class_subjects()

    assert len(subjects) == 1
    assert subjects[0]["subjectType"] == "class"
    assert subjects[0]["subjectId"] == "2"
    assert subjects[0]["classId"] == "2"
    assert subjects[0]["courseId"] == "1"
    assert subjects[0]["id"] == "1_2_3"


def test_chaoxing_signin_get_active_tasks_filters_by_class_and_active_id():
    client = ChaoxingSigninClient()
    now_ms = int(time.time() * 1000)

    def _activities(course_id, class_id):
        if class_id == "2":
            return [
                {"id": "11", "status": 1, "otherId": 4, "nameOne": "Class Location", "startTime": now_ms},
                {"id": "12", "status": 1, "otherId": 4, "nameOne": "Other Active", "startTime": now_ms},
            ]
        return [{"id": "11", "status": 1, "otherId": 4, "nameOne": "Wrong Class", "startTime": now_ms}]

    with patch.object(
        client,
        "get_courses",
        return_value=[
            {"courseId": "1", "classId": "2", "courseName": "Demo Course"},
            {"courseId": "3", "classId": "4", "courseName": "Other Course"},
        ],
    ), patch.object(client, "_get_course_activity_list", side_effect=_activities):
        tasks = client.get_active_tasks(class_filters=["2"], active_id="11", expected_type="location")

    assert len(tasks) == 1
    assert tasks[0]["subjectType"] == "class"
    assert tasks[0]["activeId"] == "11"
    assert tasks[0]["classId"] == "2"
    assert tasks[0]["rawCourseId"] == "1"
    assert tasks[0]["taskId"] == "1:2:11"
    assert "mobilelearn.chaoxing.com/pptSign/stuSignajax" in tasks[0]["remoteEndpoints"]["endpoints"]["submitSign"]["url"]


def test_chaoxing_remote_sign_endpoints_are_real_chaoxing_urls():
    endpoints = build_remote_sign_endpoints(
        course_id="1",
        class_id="2",
        active_id="11",
        uid="99",
        fid="88",
    )

    assert endpoints["directBrowserRequest"] is True
    assert endpoints["browserRequestMode"] == "remote-direct"
    assert "mobilelearn.chaoxing.com/v2/apis/active/student/activelist" in endpoints["endpoints"]["activities"]["url"]
    assert "courseId=1" in endpoints["endpoints"]["activities"]["url"]
    assert "classId=2" in endpoints["endpoints"]["activities"]["url"]
    assert "mobilelearn.chaoxing.com/newsign/preSign" in endpoints["endpoints"]["preSign"]["url"]
    assert "mobilelearn.chaoxing.com/pptSign/stuSignajax" in endpoints["endpoints"]["submitSign"]["url"]


def test_chaoxing_signin_get_courses_traverse_folder_and_dedup():
    client = ChaoxingSigninClient()

    root_html = """
    <ul class="file-list">
      <li fileid="10"><input class="rename-input" value="Folder 10" /></li>
      <li fileid="20"><input class="rename-input" value="Folder 20" /></li>
    </ul>
    <div id="course_100_200"><a href="/p?cpi=300" title="Root Course">Root Course</a></div>
    <div id="course_100_200"><a href="/p?cpi=300" title="Root Course Duplicate">Root Course Duplicate</a></div>
    """
    folder_10_html = """
    <div id="course_100_200"><a href="/p?cpi=300" title="Root Course">Root Course</a></div>
    <div id="course_101_201"><a href="/p?cpi=301" title="Folder 10 Course">Folder 10 Course</a></div>
    """
    folder_20_html = """
    <div id="course_101_201"><a href="/p?cpi=301" title="Folder 10 Course">Folder 10 Course</a></div>
    <div id="course_102_202"><a href="/p?cpi=302" title="Folder 20 Course">Folder 20 Course</a></div>
    """

    post_calls = []

    def _post_side_effect(*args, **kwargs):
        folder_id = int((kwargs.get("data") or {}).get("courseFolderId", 0))
        post_calls.append(folder_id)
        resp = Mock()
        resp.text = {
            10: folder_10_html,
            20: folder_20_html,
        }.get(folder_id, root_html)
        return resp

    with patch.object(client.session, "post", side_effect=_post_side_effect), patch.object(
        client.session,
        "get",
        return_value=Mock(
            text='<ul class="file-list"><li fileid="10"><input class="rename-input" value="F1" /></li><li fileid="20"><input class="rename-input" value="F2" /></li></ul>'
        ),
    ):
        courses = client.get_courses()

    assert post_calls
    assert post_calls[0] == 0

    unique_pairs = {(item["courseId"], item["classId"]) for item in courses}
    assert len(unique_pairs) == len(courses)

    assert post_calls == [0, 10, 20]
    assert unique_pairs == {("100", "200"), ("101", "201"), ("102", "202")}


def test_chaoxing_signin_parse_courses_hidden_input_fallback():
    client = ChaoxingSigninClient()
    content = """
    <div class="course" info="demo" roleid="0">
      <input class="courseId" value="555" />
      <input class="clazzId" value="777" />
      <a href="/mycourse/studentcourse?courseid=555&clazzid=777&cpi=888&ut=s">
        <span class="course-name" title="Hidden Input Course">Hidden Input Course</span>
      </a>
    </div>
    """

    courses = client._parse_courses(content)

    assert len(courses) == 1
    assert courses[0]["courseId"] == "555"
    assert courses[0]["classId"] == "777"
    assert courses[0]["cpi"] == "888"
    assert courses[0]["courseName"] == "Hidden Input Course"


def test_chaoxing_signin_parse_courses_json_name_fallback():
    client = ChaoxingSigninClient()
    content = """
    <script>
      var courseData = [
        {"courseId":"901","classId":"902","cpi":"903","courseName":"JSON Named Course"}
      ];
    </script>
    """

    courses = client._parse_courses(content)

    assert len(courses) == 1
    assert courses[0]["courseId"] == "901"
    assert courses[0]["classId"] == "902"
    assert courses[0]["cpi"] == "903"
    assert courses[0]["courseName"] == "JSON Named Course"


def test_chaoxing_signin_parse_courses_anchor_text_name_fallback():
    client = ChaoxingSigninClient()
    content = """
    <div class="course" id="course_701_702">
      <a href="/mycourse/studentcourse?courseid=701&clazzid=702&cpi=703&ut=s">Real Course Name</a>
    </div>
    """

    courses = client._parse_courses(content)

    assert len(courses) == 1
    assert courses[0]["courseId"] == "701"
    assert courses[0]["classId"] == "702"
    assert courses[0]["cpi"] == "703"
    assert courses[0]["courseName"] == "Real Course Name"
