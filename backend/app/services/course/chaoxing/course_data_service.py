"""Course data fetching service for Chaoxing."""

from concurrent.futures import ThreadPoolExecutor

from loguru import logger

from .constants import CARD_FETCH_WORKERS
from .decode import decode_course_card, decode_course_folder, decode_course_point
from .rate_limiter import RateLimiter

# API URL constants
COURSE_INTERACTION_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
COURSE_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
KNOWLEDGE_CARDS_URL = "https://mooc1.chaoxing.com/mooc-ans/knowledge/cards"


class ChaoxingCourseDataService:
    """Fetches course lists, chapter points, and job lists."""

    def __init__(self, course_service, rate_limiter: RateLimiter, study_emptypage_func, session_manager=None):
        self.course_service = course_service
        self.rate_limiter = rate_limiter
        self._study_emptypage = study_emptypage_func
        self.session_manager = session_manager

    def get_course_list(self):
        _session = self.session_manager.get_session()
        course_list = self.course_service.get_course_list()

        _interaction_url = COURSE_INTERACTION_URL
        _interaction_resp = _session.get(_interaction_url)
        course_folder = decode_course_folder(_interaction_resp.text)

        _url = COURSE_LIST_URL
        for folder in course_folder:
            _data = {
                "courseType": 1,
                "courseFolderId": folder["id"],
                "query": "",
                "superstarClass": 0,
            }
            from .decode import decode_course_list

            _resp = _session.post(_url, data=_data)
            course_list += decode_course_list(_resp.text)
        return course_list

    def get_course_point(self, _courseid, _clazzid, _cpi):
        _session = self.session_manager.get_session()
        _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={_courseid}&clazzid={_clazzid}&cpi={_cpi}&ut=s"
        logger.trace("开始读取课程所有章节...")
        _resp = _session.get(_url)
        logger.info("课程章节读取成功...")
        return decode_course_point(_resp.text)

    def get_job_list(self, course: dict, point: dict) -> tuple[list[dict], dict]:
        """
        Fetch all job/task items for a specific course chapter.

        Args:
            course: Course information dict with courseId, clazzId, cpi
            point: Chapter/point information dict with id

        Returns:
            Tuple of (job_list: list of job dicts, job_info: metadata dict)
        """
        _session = self.session_manager.get_session()
        self.rate_limiter.limit_rate()
        job_list = []
        job_info = {}
        cards_params = {
            "clazzid": course["clazzId"],
            "courseid": course["courseId"],
            "knowledgeid": point["id"],
            "ut": "s",
            "cpi": course["cpi"],
            "v": "2025-0424-1038-3",
            "mooc2": 1,
        }

        logger.trace("开始读取章节所有任务点...")

        def fetch_card(num):
            params = cards_params.copy()
            params["num"] = num
            return _session.get(KNOWLEDGE_CARDS_URL, params=params)

        with ThreadPoolExecutor(max_workers=CARD_FETCH_WORKERS) as executor:
            responses = list(executor.map(fetch_card, "0123456"))

        for _resp in responses:
            if _resp.status_code != 200:
                logger.error(f"未知错误: {_resp.status_code} 正在跳过")
                logger.error(_resp.text)
                return [], {}

            _job_list, _job_info = decode_course_card(_resp.text)
            if _job_info.get("notOpen", False):
                logger.info("该章节未开放")
                return [], _job_info

            job_list += _job_list
            job_info.update(_job_info)

        if not job_list:
            self._study_emptypage(course, point)
        logger.info("章节任务点读取成功...")

        return job_list, job_info
