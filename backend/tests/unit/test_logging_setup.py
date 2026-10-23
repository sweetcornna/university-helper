"""The loguru → stdlib bridge must keep tracebacks."""

import logging

from loguru import logger as loguru_logger

from app.core import logging_setup


def test_loguru_exception_reaches_stdlib_with_traceback(caplog):
    sink_id = loguru_logger.add(logging_setup._StdlibSink(), format="{message}", backtrace=False, diagnose=False)
    try:
        with caplog.at_level(logging.ERROR):
            try:
                raise ValueError("Invalid Chaoxing task card mArg object")
            except ValueError:
                loguru_logger.exception("Chapter processing crashed: {}", "2.1 第一节")
    finally:
        loguru_logger.remove(sink_id)

    record = next(r for r in caplog.records if "Chapter processing crashed" in r.getMessage())
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError
    assert "Invalid Chaoxing task card mArg object" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text


def test_loguru_message_without_exception_has_no_exc_info(caplog):
    sink_id = loguru_logger.add(logging_setup._StdlibSink(), format="{message}")
    try:
        with caplog.at_level(logging.INFO):
            loguru_logger.info("plain message")
    finally:
        loguru_logger.remove(sink_id)

    record = next(r for r in caplog.records if r.getMessage() == "plain message")
    assert record.exc_info is None
