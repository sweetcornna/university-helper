from app.services.course.chaoxing.course_portal_service import (
    ChaoxingCourseContext,
    chaoxing_course_portal_service,
)


def test_portal_urls_match_desktop_client_routes():
    context = ChaoxingCourseContext(
        course_id="1001",
        class_id="2002",
        cpi="3003",
        name="Course A",
        fid="181",
        stuenc="stu-enc",
        enc="shell-enc",
        openc="open-enc",
    )

    payload = chaoxing_course_portal_service.build_portal_urls(context)
    tabs = {tab["key"]: tab for tab in payload["tabs"]}

    assert "mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu" in tabs["resources"]["shellUrl"]
    assert "pageHeader=3" in tabs["resources"]["shellUrl"]
    assert "mobilelearn.chaoxing.com/page/active/stuActiveList" in tabs["activities"]["frameUrl"]
    assert "mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse" in tabs["chapters"]["frameUrl"]
    assert "mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist" in tabs["resources"]["frameUrl"]
    assert "mooc1.chaoxing.com/mooc2/work/list" in tabs["homework"]["frameUrl"]
    assert "mooc1.chaoxing.com/exam-ans/mooc2/exam/exam-list" in tabs["tests"]["frameUrl"]
    assert "openc=open-enc" in tabs["tests"]["frameUrl"]
    assert "mobilelearn.chaoxing.com/v2/apis/active/student/activelist" in tabs["activities"]["remoteApiUrl"]
    assert tabs["activities"]["remoteRequest"]["url"] == tabs["activities"]["remoteApiUrl"]
    assert "proxyEndpoint" not in tabs["activities"]
    assert tabs["resources"]["directBrowserRequest"] is True
    assert tabs["resources"]["remoteRequest"]["url"] == tabs["resources"]["remoteUrl"]


def test_resolve_course_uses_course_list_cpi_when_selector_omits_it():
    context = chaoxing_course_portal_service.resolve_course(
        "1001_2002",
        [{"courseId": "1001", "classId": "2002", "cpi": "3003", "courseName": "Course A"}],
    )

    assert context.selector == "1001_2002_3003"
    assert context.name == "Course A"


def test_parse_activities_from_mobilelearn_payload():
    activities = chaoxing_course_portal_service.parse_activities(
        {
            "data": {
                "activeList": [
                    {
                        "id": 99,
                        "nameOne": "课堂签到",
                        "otherId": 4,
                        "status": 1,
                        "startTime": 1710000000000,
                    }
                ]
            }
        }
    )

    assert activities == [
        {
            "id": "99",
            "title": "课堂签到",
            "type": "location",
            "otherId": 4,
            "status": "active",
            "statusCode": 1,
            "startTime": "2024-03-09T16:00:00+00:00",
            "endTime": None,
            "raw": {
                "id": 99,
                "nameOne": "课堂签到",
                "otherId": 4,
                "status": 1,
                "startTime": 1710000000000,
            },
        }
    ]


def test_parse_resource_links_from_html():
    html = """
    <ul>
      <li><a href="/file/download?objectid=1" title="第一讲课件.pdf">下载</a></li>
      <li><a href="/file/preview/report.docx">课程资料 docx</a><span>已完成</span></li>
      <li><a href="#">下一页</a></li>
    </ul>
    """

    items = chaoxing_course_portal_service.parse_html_tab(
        "resources",
        html,
        "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist",
    )

    assert [item["title"] for item in items] == ["第一讲课件.pdf", "课程资料 docx"]
    assert items[0]["url"].startswith("https://mooc2-ans.chaoxing.com/file/download")
