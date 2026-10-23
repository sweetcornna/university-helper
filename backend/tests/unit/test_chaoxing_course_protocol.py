"""Regression coverage for the Chaoxing course HTTP and HTML contracts."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.course.chaoxing.constants import StudyResult
from app.services.course.chaoxing.course_data_service import ChaoxingCourseDataService
from app.services.course.chaoxing.course_service import ChaoxingCourseService
from app.services.course.chaoxing.decode import decode_course_card, decode_course_list, decode_course_point
from app.services.course.chaoxing.learning import process_job


def test_course_list_uses_upstream_interaction_referer():
    session = Mock()
    session.post.return_value.text = "<html></html>"
    service = ChaoxingCourseService(session_manager=SimpleNamespace(get_session=lambda: session))

    assert service.get_course_list() == []

    assert session.post.call_args.kwargs["headers"]["Referer"] == (
        "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction" "?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans"
    )


def test_course_list_parses_terminal_cpi_and_optional_display_fields():
    html = """
    <div class="course" id="course-1" info="info-1" roleid="3">
      <input class="clazzId" value="22"><input class="courseId" value="11">
      <a href="/mycourse/stu?courseid=11&amp;clazzid=22&amp;cpi=33"><img></a>
      <span class="course-name">English Course</span>
      <p class="color3">Teacher A</p>
    </div>
    """

    assert decode_course_list(html) == [
        {
            "id": "course-1",
            "info": "info-1",
            "roleid": "3",
            "clazzId": "22",
            "courseId": "11",
            "cpi": "33",
            "title": "English Course",
            "desc": "",
            "teacher": "Teacher A",
        }
    ]


def test_chapter_parser_skips_non_knowledge_rows():
    html = """
    <div class="chapter_unit"><ul>
      <li><div id="chapter_heading">Chapter one</div></li>
      <li><span>Decorative row</span></li>
      <li><div id="cur123"><a class="clicktitle">Lesson one</a>
        <input class="knowledgeJobCount" value="2">
      </div></li>
    </ul></div>
    """

    assert decode_course_point(html)["points"] == [
        {"id": "123", "title": "Lesson one", "jobCount": "2", "has_finished": False, "need_unlock": False}
    ]


@pytest.mark.parametrize("pretty", [False, True])
def test_task_card_json_preserves_spaces_newlines_and_embedded_delimiters(pretty):
    title = 'Unit 1: English grammar }; "quoted"'
    data = {
        "defaults": {"knowledgeid": "123", "cpi": "33"},
        "attachments": [
            {
                "type": "video",
                "job": True,
                "jobid": "job-1",
                "mid": "mid-1",
                "objectId": "obj-1",
                "property": {"name": title},
                "otherInfo": "nodeId_123-cpi_33",
            },
        ],
    }
    html = f"<script>var mArg = {json.dumps(data, indent=2 if pretty else None)};</script>"

    jobs, info = decode_course_card(html)

    assert len(jobs) == 1
    assert jobs[0]["name"] == title
    assert info["knowledgeid"] == "123"


def test_task_card_with_invalid_assignment_is_not_an_empty_chapter():
    with pytest.raises(ValueError, match="mArg"):
        decode_course_card('<script>var mArg = {"attachments": broken};</script>')


def test_chapter_jobs_keep_each_cards_submission_tokens():
    session = Mock()

    def get(url, params=None):
        num = params["num"]
        data = {
            "defaults": {"knowledgeid": "123", "ktoken": f"token-{num}", "cardid": f"card-{num}"},
            "attachments": [{"type": "workid", "job": True, "jobid": f"work-{num}", "enc": f"enc-{num}"}],
        }
        return SimpleNamespace(status_code=200, text=f"<script>mArg={json.dumps(data)};</script>")

    session.get.side_effect = get
    service = ChaoxingCourseDataService(
        Mock(), Mock(), Mock(), session_manager=SimpleNamespace(get_session=lambda: session)
    )
    jobs, info = service.get_job_list({"clazzId": "22", "courseId": "11", "cpi": "33"}, {"id": "123"})
    chaoxing = SimpleNamespace(study_work=Mock(return_value=StudyResult.SUCCESS))

    for job in jobs:
        assert process_job(chaoxing, {"title": "course"}, job, info, 1) == StudyResult.SUCCESS
        tokens = chaoxing.study_work.call_args.args[2]
        assert tokens["ktoken"] == "token-" + job["jobid"].removeprefix("work-")
        assert tokens["cardid"] == "card-" + job["jobid"].removeprefix("work-")


def test_unparsed_task_cards_do_not_trigger_empty_page_study():
    session = Mock()
    session.get.return_value = SimpleNamespace(status_code=200, text="<html>Login required</html>")
    study_empty = Mock()
    service = ChaoxingCourseDataService(
        Mock(), Mock(), study_empty, session_manager=SimpleNamespace(get_session=lambda: session)
    )

    assert service.get_job_list({"clazzId": "22", "courseId": "11", "cpi": "33"}, {"id": "123"}) == ([], {})

    study_empty.assert_not_called()


def _real_cards_page(data):
    """Shape of the live mooc1 knowledge/cards page: mArg is declared as "" first."""
    return f"""
    <script type="text/javascript">
        var clickArray = [];
        var mArg = "";
        var courseid = "";
        var knowledgeid = "";
        try{{
            mArg = {json.dumps(data, ensure_ascii=False)};
            courseid = 255665643;
            knowledgeid = 1026884511;
        }}catch(e){{
            console.log(e)
        }}
        var  attachments = mArg.attachments;
    </script>
    """


_REAL_CARD = {
    "hiddenConfig": False,
    "attachments": [
        {
            "type": "video",
            "job": True,
            "jobid": "1756474100488340",
            "mid": "mid-1",
            "objectId": "obj-1",
            "otherInfo": "nodeId_1026884511-cpi_492936718-rt_d&courseId=255665643",
            "property": {"name": "2.1 第一节.mp4", "type": ".mp4"},
        }
    ],
    "defaults": {"knowledgeid": 1026884511, "ktoken": "kt", "cardid": 1000302623, "cpi": 492936718},
}


def test_task_card_page_that_declares_mArg_as_empty_string_first():
    # Regression for v1.6.0: the decoder took the first `mArg = ""` and raised
    # "Invalid Chaoxing task card mArg object" on every real chapter page.
    jobs, info = decode_course_card(_real_cards_page(_REAL_CARD))

    assert [job["jobid"] for job in jobs] == ["1756474100488340"]
    assert jobs[0]["name"] == "2.1 第一节.mp4"
    assert info["knowledgeid"] == 1026884511
    assert info["ktoken"] == "kt"


def test_task_card_page_with_only_the_empty_declaration_is_not_a_crash():
    jobs, info = decode_course_card('<script>var mArg = "";</script>')

    assert (jobs, info) == ([], {})


def test_chapter_job_list_reads_real_cards_pages():
    session = Mock()
    session.get.return_value = SimpleNamespace(status_code=200, text=_real_cards_page(_REAL_CARD))
    service = ChaoxingCourseDataService(
        Mock(), Mock(), Mock(), session_manager=SimpleNamespace(get_session=lambda: session)
    )

    jobs, info = service.get_job_list({"clazzId": "22", "courseId": "11", "cpi": "33"}, {"id": "123"})

    assert jobs and all(job["jobid"] == "1756474100488340" for job in jobs)
    assert info["cardid"] == 1000302623
