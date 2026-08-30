"""Constants for Chaoxing service"""

from enum import Enum


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


# Preserve the public/pickle module path while keeping the definition in this
# dependency-free module. ``client`` re-exports this exact class.
StudyResult.__module__ = "app.services.course.chaoxing.client"


# Rate limiting
DEFAULT_RATE_LIMIT = 0.5
VIDEO_LOG_RATE_LIMIT = 2.0

# Video processing
VIDEO_WAIT_TIME_MIN = 30
VIDEO_WAIT_TIME_MAX = 90
VIDEO_SLEEP_THRESHOLD = 1

# Retry settings
MAX_FORBIDDEN_RETRY = 2
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY = 1

# Thread pool settings
CARD_FETCH_WORKERS = 7
DEFAULT_AI_CONCURRENCY = 3

# Time multipliers
MILLISECONDS_MULTIPLIER = 1000
