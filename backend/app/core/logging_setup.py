"""Logging configuration.

Goal: have a single logging pipeline so uvicorn access logs, our app logs,
and library logs share format/level/sink. We use stdlib `logging` as the
canonical layer and intercept loguru's stream so legacy callers that
`from loguru import logger` still flow through stdlib handlers.

Call `configure_logging()` once at app start (see app/main.py lifespan).
"""

from __future__ import annotations

import logging
import os
import sys
from logging.config import dictConfig

_CONFIGURED = False


def _log_level() -> str:
    return (os.getenv("LOG_LEVEL") or "INFO").upper()


def _formatter_name() -> str:
    return "json" if (os.getenv("LOG_FORMAT") or "").lower() == "json" else "plain"


_DICT_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {
            "format": "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "json": {
            "()": "logging.Formatter",
            "format": '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": _formatter_name(),
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["stdout"], "level": "WARNING", "propagate": False},
        "app": {"handlers": ["stdout"], "level": _log_level(), "propagate": False},
        "chaoxing": {"handlers": ["stdout"], "level": _log_level(), "propagate": False},
    },
    "root": {"handlers": ["stdout"], "level": _log_level()},
}


def configure_logging() -> None:
    """Wire stdlib logging and bridge loguru into it. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    dictConfig(_DICT_CONFIG)
    _bridge_loguru()
    _CONFIGURED = True


def _bridge_loguru() -> None:
    """Forward loguru records into stdlib logging so we have a single sink.

    Recipe from loguru's docs ("Entirely compatible with standard logging").
    Wrapped in try/except so the app keeps booting if loguru isn't installed.
    """
    try:
        from loguru import logger as loguru_logger
    except Exception:  # pragma: no cover
        return

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
            try:
                level = loguru_logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            loguru_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    # Send loguru → stdlib instead, so there's only one sink format.
    loguru_logger.remove()
    loguru_logger.add(
        _StdlibSink(),
        level=_log_level(),
        format="{message}",
        backtrace=False,
        diagnose=False,
    )


class _StdlibSink:  # pragma: no cover
    """Treat loguru records as stdlib log records."""

    def __call__(self, message) -> None:
        record = message.record
        logger = logging.getLogger(record["name"] or "loguru")
        logger.log(record["level"].no, record["message"])
