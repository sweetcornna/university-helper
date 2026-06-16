from enum import Enum

from .answer import Tiku
from .auth_service import ChaoxingAuthService
from .constants import (
    DEFAULT_RATE_LIMIT,
    VIDEO_LOG_RATE_LIMIT,
)
from .course_data_service import ChaoxingCourseDataService
from .course_service import ChaoxingCourseService
from .quiz_service import ChaoxingQuizService
from .rate_limiter import RateLimiter
from .session_manager import SessionManager
from .video_service import ChaoxingVideoService
from .work_legacy_service import ChaoxingWorkLegacyService


class Account:
    username = None
    password = None
    last_login = None
    isSuccess = None

    def __init__(self, _username, _password):
        self.username = _username
        self.password = _password


class StudyResult(Enum):
    SUCCESS = 0
    FORBIDDEN = 1
    ERROR = 2
    TIMEOUT = 3
    CANCELLED = 4

    def is_success(self):
        return self == StudyResult.SUCCESS

    def is_failure(self):
        return self in {StudyResult.FORBIDDEN, StudyResult.ERROR, StudyResult.TIMEOUT}

    def is_cancelled(self):
        return self == StudyResult.CANCELLED


class Chaoxing:
    def __init__(self, account: Account = None, tiku: Tiku = None, **kwargs):
        self.account = account
        self.tiku = tiku
        self.kwargs = kwargs
        self.rollback_times = 0
        self.rate_limiter = RateLimiter(DEFAULT_RATE_LIMIT)
        self.video_log_limiter = RateLimiter(VIDEO_LOG_RATE_LIMIT)

        # Each Chaoxing instance owns its own session for multi-tenant isolation.
        self.session_manager = SessionManager()

        self.auth_service = ChaoxingAuthService(account, session_manager=self.session_manager)
        self.course_service = ChaoxingCourseService(session_manager=self.session_manager)
        self.quiz_service = ChaoxingQuizService(tiku, self.rollback_times, kwargs, session_manager=self.session_manager)

        self.video_service = ChaoxingVideoService(
            get_fid_func=self.get_fid,
            get_uid_func=self.get_uid,
            rate_limiter=self.rate_limiter,
            video_log_limiter=self.video_log_limiter,
            session_manager=self.session_manager,
        )
        self.course_data_service = ChaoxingCourseDataService(
            course_service=self.course_service,
            rate_limiter=self.rate_limiter,
            study_emptypage_func=self.study_emptypage,
            session_manager=self.session_manager,
        )
        self.work_legacy_service = ChaoxingWorkLegacyService(
            tiku=tiku,
            rollback_times=self.rollback_times,
            kwargs=kwargs,
            session_manager=self.session_manager,
        )

    # ------------------------------------------------------------------
    # Auth proxies
    # ------------------------------------------------------------------

    def login(self, login_with_cookies=False):
        return self.auth_service.login(login_with_cookies)

    def get_fid(self):
        return self.auth_service.get_fid()

    def get_uid(self):
        return self.auth_service.get_uid()

    # ------------------------------------------------------------------
    # Course data proxies
    # ------------------------------------------------------------------

    def get_course_list(self):
        return self.course_data_service.get_course_list()

    def get_course_point(self, _courseid, _clazzid, _cpi):
        return self.course_data_service.get_course_point(_courseid, _clazzid, _cpi)

    def get_job_list(self, course: dict, point: dict) -> tuple[list[dict], dict]:
        return self.course_data_service.get_job_list(course, point)

    # ------------------------------------------------------------------
    # Video proxies
    # ------------------------------------------------------------------

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        return self.video_service.get_enc(clazzId, jobid, objectId, playingTime, duration, userid)

    def video_progress_log(
        self, _session, _course, _job, _job_info, _dtoken, _duration, _playingTime, _type="Video", headers=None
    ):
        return self.video_service.video_progress_log(
            _session, _course, _job, _job_info, _dtoken, _duration, _playingTime, _type, headers=headers
        )

    def _refresh_video_status(self, session, job, _type):
        return self.video_service._refresh_video_status(session, job, _type)

    def _recover_after_forbidden(self, session, job, _type):
        return self.video_service._recover_after_forbidden(session, job, _type)

    def study_video(
        self, _course, _job, _job_info, _speed=1.0, _type="Video", progress_callback=None, should_stop=None
    ):
        return self.video_service.study_video(_course, _job, _job_info, _speed, _type, progress_callback, should_stop)

    # ------------------------------------------------------------------
    # Work / quiz proxies
    # ------------------------------------------------------------------

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        result = self.quiz_service.study_work(_course, _job, _job_info)
        return StudyResult.SUCCESS if result else StudyResult.ERROR

    def _study_work_legacy(self, _course, _job, _job_info) -> StudyResult:
        return self.work_legacy_service.study_work(_course, _job, _job_info)

    # ------------------------------------------------------------------
    # Course service proxies
    # ------------------------------------------------------------------

    def study_document(self, _course, _job) -> StudyResult:
        result = self.course_service.study_document(_course, _job)
        return StudyResult.SUCCESS if result else StudyResult.ERROR

    def study_read(self, _course, _job, _job_info) -> StudyResult:
        result = self.course_service.study_read(_course, _job, _job_info)
        return StudyResult.SUCCESS if result else StudyResult.ERROR

    def study_emptypage(self, _course, point):
        result = self.course_service.study_emptypage(_course, point)
        return StudyResult.SUCCESS if result else StudyResult.ERROR
