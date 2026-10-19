from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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


@pytest.mark.parametrize("tab_key", ["chapters", "resources", "homework", "tests"])
@pytest.mark.parametrize("response_kind", ["redirect", "form", "unauthorized"])
def test_fetch_tab_rejects_expired_login_instead_of_returning_empty_or_fake_items(tab_key, response_kind):
    response = SimpleNamespace(
        status_code=401 if response_kind == "unauthorized" else 200,
        url="https://passport2.chaoxing.com/login" if response_kind == "redirect" else "https://mooc1.chaoxing.com/",
        text=(
            '<form id="loginForm"><input id="phone" name="uname"><input id="pwd" type="password">'
            '<a href="/v5/toCustomer">客服</a><a href="javaScript:void(0)">忘记密码？</a></form>'
            if response_kind == "form"
            else "<html></html>"
        ),
        headers={},
    )
    session = Mock()
    session.get.return_value = response

    with pytest.raises(RuntimeError, match="登录.*失效|重新登录"):
        chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), tab_key)

    assert session.get.call_count == 1


@pytest.mark.parametrize("tab_key", ["resources", "homework", "tests"])
def test_parse_html_tab_ignores_navigation_and_exam_dialog_templates(tab_key):
    html = """
    <div class="navigation"><a href="/mycourse/stu">课程首页</a><a href="/help">帮助中心</a></div>
    <div style="display:none">
      <a href="javascript:enterExam()">进入考试</a><a href="">知道了</a>
      <a href="javaScript:void(0)">重新识别</a><a href="#">继续作答</a>
      <a href="javascript:;">退出考试</a>
      <a href="/keeper/appeal/page/submit?clazzId=22&amp;examId=&amp;type=4">申诉</a>
    </div>
    """

    assert chaoxing_course_portal_service.parse_html_tab(tab_key, html, "https://mooc1.chaoxing.com/") == []


def test_resource_links_require_content_urls_and_do_not_infer_file_types_from_domains():
    html = """
    <a href="https://beian.miit.gov.cn">京ICP备10040544号-2</a>
    <a href="https://homewh.chaoxing.com/agree/privacyPolicy?appId=900001">《隐私政策》</a>
    <a href="/file/download?objectid=1" title="教材.pdf">下载</a>
    <a href="/file/preview/report.docx">课程资料 docx</a>
    <a href="/mooc2/resource/view?id=2" title="参考资料">打开</a>
    """

    items = chaoxing_course_portal_service.parse_html_tab("resources", html, "https://mooc2-ans.chaoxing.com/")

    assert [item["title"] for item in items] == ["教材.pdf", "课程资料 docx", "参考资料"]
    assert items[1]["fileType"] == "docx"
    assert all(item.get("fileType") != "cn" for item in items)


@pytest.mark.parametrize("tab_key", ["chapters", "resources", "homework", "tests"])
@pytest.mark.parametrize("message", ["无效的参数", "无权限的操作！"])
def test_fetch_tab_rejects_upstream_error_pages(tab_key, message):
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200,
        url="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/list",
        headers={},
        text=f'<div class="nullMain"><div class="word_null"><p>{message}</p></div></div>',
    )

    with pytest.raises(RuntimeError, match=message):
        chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), tab_key)


def _denied_then(navigation, retry_html=None):
    """Session whose first tab request is denied; the course navigation decides what happens next."""
    denied = SimpleNamespace(
        status_code=200,
        url="https://mooc1.chaoxing.com/mooc2/work/list",
        headers={},
        text='<div class="nullMain"><div class="word_null"><p>无权限的操作！</p></div></div>',
    )
    nav = SimpleNamespace(json=lambda: {"status": True, "navigationList": navigation})
    retried = SimpleNamespace(status_code=200, url="", headers={}, text=retry_html or "")
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if "stu-base-info" in url:
            return nav
        return denied if len(calls) == 1 else retried

    return SimpleNamespace(get=get), calls


def test_denied_homework_hidden_from_students_is_reported_as_unavailable_not_an_error():
    session, calls = _denied_then(
        [
            {"translateName": "章节", "linkUrl": "/mooc2-ans/mycourse/studentcourse?courseid=11"},
            {
                "translateName": "学习资源库",
                "children": [{"translateName": "资料", "linkUrl": "/mooc2-ans/coursedata/stu-datalist?courseid=11"}],
            },
        ]
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "homework")

    assert payload["homework"] == []
    assert payload["unavailable"] is True
    assert payload["message"] == "这门课没有向学生开放「作业」栏目"
    assert len(calls) == 2


def test_denied_tab_is_retried_with_the_navigation_url_that_carries_course_tokens():
    nav_url = "https://mooc1.chaoxing.com/mooc2/exam/exam-list?courseid=11&clazzid=22&enc=nav-enc&openc=nav-openc"
    session, calls = _denied_then(
        [{"translateName": "更多功能", "children": [{"translateName": "自测", "linkUrl": nav_url}]}],
        retry_html='<div class="task-list"><div class="null-data">暂无考试</div></div>',
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "tests")

    assert calls[-1] == nav_url
    assert payload["url"] == nav_url
    assert payload["message"] == "暂无考试"


def test_denied_tab_still_fails_when_the_navigation_link_is_denied_too():
    session, _ = _denied_then(
        [{"translateName": "作业", "linkUrl": "https://mooc1.chaoxing.com/mooc2/work/list?enc=nav"}],
        retry_html='<div class="nullMain"><div class="word_null"><p>无权限的操作！</p></div></div>',
    )

    with pytest.raises(RuntimeError, match="无权限"):
        chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "homework")


def test_fetch_resources_accepts_the_real_empty_file_list():
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200,
        headers={},
        text="""<div class="dataHead"><ul class="dataHead_th"><li>名称</li></ul></div>
        <div class="dataBody"><div tabindex="0" role="option" class="NoResult">暂无文件</div></div>""",
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "resources")

    assert payload["resources"] == []
    assert payload["message"] == "暂无文件"


def test_fetch_chapters_lists_units_that_have_no_task_points():
    unit = """<div class="chapter_unit"><div class="chapter_item"><div class="catalog_name newCatalog_name">
      <a class="clicktitle"><span title="{0}"> {0} </span></a></div></div></div>"""
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200,
        headers={},
        text=f'<div id="fanyaChapter"><div class="chapter_td">{unit.format("导言")}{unit.format("辛亥革命")}</div></div>',
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "chapters")

    assert [item["title"] for item in payload["chapters"]] == ["导言", "辛亥革命"]
    assert payload["message"] == "这门课的章节没有任务点"


@pytest.mark.parametrize("message", ["该课程下的全部章节内容已被教师设置隐藏", "暂无章节内容"])
def test_fetch_chapters_keeps_the_upstream_empty_state_message(message):
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200,
        headers={},
        text=f'<div id="fanyaChapter"><div class="chapter_body"><div class="nodata"><p>{message}</p></div></div></div>',
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "chapters")

    assert payload["chapters"] == []
    assert payload["message"] == message


def test_fetch_tests_keeps_the_real_empty_state_and_ignores_dialogs():
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200,
        headers={},
        text="""<div class="task-list"><div class="null-data">暂无考试</div></div>
        <div class="maskDiv"><a href="javascript:;" onclick="startTest()">进入考试</a>
        <a href="/keeper/appeal/page/submit?examId=&amp;type=4">申诉</a></div>""",
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "tests")

    assert payload["tests"] == []
    assert payload["message"] == "暂无考试"


def test_exam_rows_use_the_title_and_status_instead_of_action_labels():
    html = """
    <div class="bottomList"><ul>
      <li id="exam-101">
        <div class="right-content"><p title="期末考试">期末考试</p><p class="status">已完成</p></div>
        <a href="javascript:;" onclick="viewPaper('201')">查看</a>
      </li>
      <li id="exam-102">
        <div class="right-content"><p>期中测验</p><p class="status">未开始</p></div>
        <a href="javascript:;" onclick="goTest('11','102','202')">进入考试</a>
      </li>
    </ul></div>
    <div class="maskDiv"><a href="javascript:;">知道了</a></div>
    """
    base_url = "https://mooc1.chaoxing.com/exam-ans/mooc2/exam/exam-list?courseid=11&clazzid=22&cpi=33"

    items = chaoxing_course_portal_service.parse_html_tab("tests", html, base_url)

    assert [item["title"] for item in items] == ["期末考试", "期中测验"]
    assert [item["status"] for item in items] == ["completed", "pending"]
    assert [item["id"] for item in items] == ["exam-101", "exam-102"]
    assert all(item["url"] == base_url for item in items)


def test_assessment_direct_links_keep_real_items_and_ignore_list_and_appeal_links():
    base_url = "https://mooc1.chaoxing.com/"
    html = """
    <a href="/exam-ans/mooc2/exam/exam-list?examId=10">考试列表</a>
    <a href="/keeper/appeal/page/submit?examId=10">申诉</a>
    <div class="maskDiv"><a href="/exam-ans/exam/test/look?examId=99">弹窗中的查看考试</a></div>
    <ul><li><a href="/exam-ans/exam/test/look?examId=10&amp;examAnswerId=20">期末考试</a><span>已完成</span></li></ul>
    """

    items = chaoxing_course_portal_service.parse_html_tab("tests", html, base_url)

    assert len(items) == 1
    assert items[0]["title"] == "期末考试"
    assert items[0]["status"] == "completed"


def test_fetch_chapters_still_parses_real_knowledge_points():
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200,
        headers={},
        text="""<div class="chapter_unit"><ul><li><div id="cur101"><a class="clicktitle">第一节</a>
        <input class="knowledgeJobCount" value="2"><span class="bntHoverTips">已完成</span>
        </div></li></ul></div>""",
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "chapters")

    assert payload["chapters"] == [
        {"id": "101", "title": "第一节", "jobCount": "2", "has_finished": True, "need_unlock": False}
    ]
    assert "message" not in payload


@pytest.mark.parametrize("tab_key", ["chapters", "resources", "homework", "tests"])
@pytest.mark.parametrize(
    "html",
    [
        "",
        "<html><body>请完成页面验证</body></html>",
        '<div class="fanyaChapter"></div>',
        '<div class="nodata">请完成页面验证后重试</div>',
    ],
)
def test_fetch_tab_rejects_unrecognized_pages_instead_of_inventing_empty_lists(tab_key, html):
    session = Mock()
    session.get.return_value = SimpleNamespace(status_code=200, headers={}, text=html)

    with pytest.raises(RuntimeError, match="不是可识别的.*列表"):
        chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), tab_key)


@pytest.mark.parametrize("payload", [{}, {"result": False, "msg": "请登录"}, {"data": {"activeList": None}}])
def test_fetch_activities_rejects_error_payloads_instead_of_empty_success(payload):
    session = Mock()
    session.get.return_value = SimpleNamespace(status_code=200, headers={}, text="{}", json=lambda: payload)

    with pytest.raises(RuntimeError, match="不是可识别的活动列表"):
        chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "activities")


def test_resources_parse_official_rows_with_javascript_titles_and_download_actions():
    html = """
    <div class="dataBody">
      <ul class="dataBody_td" dataName="实践主题.xlsx" type="xlsx" id="101" isdown="1">
        <li class="dataBody_name_stu"><dl class="dataBody_text"><dt onclick="toOpen('title','xlsx',101)">
          <a class="rename_title" href="javascript:" title="实践主题.xlsx">实践主题.xlsx</a>
        </dt></dl><ul class="operate" style="display:none">
          <li class="operate_down"><a href="https://mooc1.chaoxing.com/coursedata/downloadData?dataId=101&amp;courseId=11&amp;classId=22&amp;cpi=33">下载</a></li>
          <li><a href="javascript:" onclick="submitCopyToCloudDisk()">保存到云盘</a></li>
        </ul></li>
        <li class="dataBody_size_stu">71.11 KB</li>
        <li class="dataBody_creater_stu">教师</li>
        <li class="dataBody_time_stu">09-13 20:50</li>
      </ul>
      <ul class="dataBody_td" dataName="课件.pptx" type="pptx" id="102" isdown="1">
        <li class="dataBody_name_stu"><a class="rename_title" href="javascript:">课件.pptx</a>
          <ul class="operate"><li class="operate_down"><a href="https://mooc1.chaoxing.com/coursedata/downloadData?dataId=102">下载</a></li></ul>
        </li><li class="dataBody_size_stu">157MB</li>
      </ul>
    </div>
    <div class="maskDiv"><a href="javascript:">保存到云盘</a></div>
    <script type="text/x-jqote-template"><ul class="dataBody_td"><a>教师课件</a></ul></script>
    """
    session = Mock()
    session.get.return_value = SimpleNamespace(status_code=200, headers={}, text=html)

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "resources")

    assert [item["title"] for item in payload["items"]] == ["实践主题.xlsx", "课件.pptx"]
    assert [item["id"] for item in payload["items"]] == ["101", "102"]
    assert [item["fileType"] for item in payload["items"]] == ["xlsx", "pptx"]
    assert payload["items"][0]["url"] == (
        "https://mooc1.chaoxing.com/coursedata/downloadData?dataId=101&courseId=11&classId=22&cpi=33"
    )
    assert "71.11 KB" in payload["items"][0]["text"]
    assert "保存到云盘" not in payload["items"][0]["text"]
    assert session.get.call_count == 1


def test_resources_without_download_keep_the_official_list_entry_and_real_title():
    html = """
    <div class="dataBody"><ul class="dataBody_td" id="101" type="pdf" isdown="0">
      <li class="dataBody_name_stu"><a class="rename_title" href="javascript:" title="只读讲义.pdf">只读讲义.pdf</a></li>
    </ul></div>
    """
    base_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist?courseid=11&clazzid=22&cpi=33"

    items = chaoxing_course_portal_service.parse_html_tab("resources", html, base_url)

    assert len(items) == 1
    assert items[0]["title"] == "只读讲义.pdf"
    assert items[0]["url"] == base_url
    assert items[0]["fileType"] == "pdf"


def test_resources_do_not_include_file_rows_from_dialog_templates():
    html = """
    <div class="dataBody"><ul class="dataBody_td" id="101" dataName="讲义.pdf" type="pdf"></ul></div>
    <div class="maskDiv"><div class="dataBody">
      <ul class="dataBody_td" id="template" dataName="示例.pdf" type="pdf"></ul>
    </div></div>
    """

    items = chaoxing_course_portal_service.parse_html_tab("resources", html, "https://mooc2-ans.chaoxing.com/")

    assert [item["id"] for item in items] == ["101"]


def test_resolve_course_preserves_card_tokens_for_portal_urls():
    context = chaoxing_course_portal_service.resolve_course(
        "11_22_33",
        [
            {
                "courseId": "11",
                "classId": "22",
                "cpi": "33",
                "enc": "shell-token",
                "stuenc": "student-token",
                "openc": "open-token",
                "fid": "181",
            },
            {"courseId": "44", "classId": "55", "enc": "other-course-token"},
        ],
    )
    tabs = {tab["key"]: tab for tab in chaoxing_course_portal_service.build_portal_urls(context)["tabs"]}

    assert "enc=shell-token" in tabs["homework"]["shellUrl"]
    assert "stuenc=student-token" in tabs["homework"]["frameUrl"]
    assert "openc=open-token" in tabs["tests"]["frameUrl"]
    assert "fid=181" in tabs["activities"]["remoteApiUrl"]
    assert "other-course-token" not in str(tabs)


def test_resources_keep_distinct_files_with_the_same_name():
    html = """
    <div class="dataBody">
      <ul class="dataBody_td" id="101" dataName="课件.pdf" type="pdf"></ul>
      <ul class="dataBody_td" id="102" dataName="课件.pdf" type="pdf"></ul>
    </div>
    """

    items = chaoxing_course_portal_service.parse_html_tab("resources", html, "https://mooc2-ans.chaoxing.com/")

    assert [item["id"] for item in items] == ["101", "102"]


def test_fetch_activities_accepts_an_explicitly_empty_list():
    session = Mock()
    session.get.return_value = SimpleNamespace(
        status_code=200, headers={}, text="{}", json=lambda: {"data": {"activeList": []}}
    )

    payload = chaoxing_course_portal_service.fetch_tab(session, ChaoxingCourseContext("11", "22", "33"), "activities")

    assert payload["activities"] == []
