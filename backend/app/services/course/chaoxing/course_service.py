import re
import time

from loguru import logger

from .decode import decode_course_list


def get_timestamp():
    return str(int(time.time() * 1000))


class ChaoxingCourseService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    def get_course_list(self):
        _session = self.session_manager.get_session()
        _url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        _data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}
        logger.trace("正在读取所有的课程列表...")

        _headers = {
            "Referer": "https://mooc2-ans.chaoxing.com/mooc-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
        }
        _resp = _session.post(_url, headers=_headers, data=_data)
        logger.info("课程列表读取完毕...")
        course_list = decode_course_list(_resp.text)
        return course_list

    def study_document(self, _course, _job):
        _session = self.session_manager.get_session()
        _url = f"https://mooc1.chaoxing.com/ananas/job/document?jobid={_job['jobid']}&knowledgeid={re.findall(r'nodeId_(.*?)-', _job['otherinfo'])[0]}&courseid={_course['courseId']}&clazzid={_course['clazzId']}&jtoken={_job['jtoken']}&_dc={get_timestamp()}"
        _resp = _session.get(_url)
        return _resp.status_code == 200

    def study_read(self, _course, _job, _job_info):
        _session = self.session_manager.get_session()
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/ananas/job/readv2",
            params={
                "jobid": _job["jobid"],
                "knowledgeid": _job_info["knowledgeid"],
                "jtoken": _job["jtoken"],
                "courseid": _course["courseId"],
                "clazzid": _course["clazzId"],
            },
        )
        if _resp.status_code != 200:
            logger.error(f"阅读任务学习失败 -> [{_resp.status_code}]{_resp.text}")
            return False
        _resp_json = _resp.json()
        logger.info(f"阅读任务学习 -> {_resp_json['msg']}")
        return True

    def study_emptypage(self, _course, point):
        _session = self.session_manager.get_session()
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": _course["courseId"],
                "clazzid": _course["clazzId"],
                "chapterId": point["id"],
                "cpi": _course["cpi"],
                "verificationcode": "",
                "mooc2": 1,
                "microTopicId": 0,
                "editorPreview": 0,
            },
        )
        if _resp.status_code != 200:
            logger.error(f"空页面任务失败 -> [{_resp.status_code}]{point['title']}")
            return False
        logger.info(f"空页面任务完成 -> {point['title']}")
        return True
