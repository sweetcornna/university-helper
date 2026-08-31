from unittest.mock import Mock

import pytest

import app.services.course.chaoxing.video_service as video_module
from app.services.course.chaoxing.video_service import ChaoxingVideoService


@pytest.mark.parametrize(
    ("rt", "status_codes"),
    [
        pytest.param("1", [403], id="403"),
        pytest.param("1", [500], id="non-200"),
        pytest.param("", [403, 500], id="rt-retry"),
    ],
)
def test_video_progress_log_redacts_sensitive_failure_context(monkeypatch, rt, status_codes):
    logger = Mock()
    monkeypatch.setattr(video_module, "logger", logger)

    dtoken = "sentinel-dtoken"
    cookie = "sentinel-cookie"
    authorization = "sentinel-authorization"
    custom_secret = "sentinel-custom-secret"
    body_secret = "sentinel-response-body"
    jobid = "sentinel-jobid"

    responses = [
        Mock(
            status_code=status_code,
            text=f"failure body: {body_secret}",
            url=f"https://mooc1.chaoxing.com/multimedia/log/a/cpi/{dtoken}?secret={custom_secret}",
        )
        for status_code in status_codes
    ]
    session = Mock(headers={"Cookie": cookie})
    session.get.side_effect = responses
    service = ChaoxingVideoService(
        get_fid_func=lambda: "fid",
        get_uid_func=lambda: "uid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
    )
    job = {
        "otherinfo": "nodeId_x",
        "jobid": jobid,
        "objectid": "objectid",
        "videoFaceCaptureEnc": "",
        "attDuration": "",
        "attDurationEnc": "",
        "rt": rt,
    }
    headers = {
        "Authorization": authorization,
        "X-Custom-Secret": custom_secret,
    }

    result = service.video_progress_log(
        session,
        {"clazzId": "clazz", "courseId": "course", "cpi": "cpi"},
        job,
        {},
        dtoken,
        10,
        1,
        headers=headers,
    )

    assert result == (False, status_codes[-1])
    assert len(session.get.call_args_list) == len(status_codes)
    for request in session.get.call_args_list:
        assert request.args[0].endswith(f"/{dtoken}")
        assert request.kwargs["headers"] == headers

    raw_log_values = [value for call in logger.mock_calls for value in (*call.args, *call.kwargs.values())]
    raw_log_text = repr(raw_log_values)
    formatted_logs = "\n".join(str(call.args[0]).format(*call.args[1:]) for call in logger.mock_calls if call.args)
    formatted_error_logs = "\n".join(str(call.args[0]).format(*call.args[1:]) for call in logger.error.call_args_list)
    assert str(status_codes[-1]) in raw_log_text
    assert jobid in raw_log_text
    assert str(status_codes[-1]) in formatted_error_logs
    assert jobid in formatted_error_logs
    assert "请求url" not in formatted_logs
    assert "请求头" not in formatted_logs
    for secret in (dtoken, cookie, authorization, custom_secret, body_secret):
        assert secret not in raw_log_text
        assert secret not in formatted_logs
