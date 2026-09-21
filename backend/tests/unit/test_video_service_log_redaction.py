import json
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


def test_video_status_refresh_redacts_non_200_response_context(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(video_module, "logger", logger)

    body_secret = "sentinel-video-refresh-body"
    url_secret = "sentinel-video-refresh-url"
    cookie_secret = "sentinel-video-refresh-cookie"
    authorization_secret = "sentinel-video-refresh-authorization"
    token_secret = "sentinel-video-refresh-token"
    jobid = "sentinel-video-refresh-jobid"
    response = Mock(
        status_code=500,
        text=f"failure body: {body_secret} token={token_secret}",
        url=f"https://example.invalid/status?secret={url_secret}",
        headers={"Cookie": cookie_secret, "Authorization": authorization_secret},
    )
    session = Mock()
    session.get.return_value = response
    service = ChaoxingVideoService(
        get_fid_func=lambda: "fid",
        get_uid_func=lambda: "uid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
    )

    result = service._refresh_video_status(session, {"objectid": "objectid", "jobid": jobid}, "Video")

    assert result is None
    assert session.get.call_count == 1
    assert session.get.call_args.kwargs["timeout"] == 8
    assert session.get.call_args.kwargs["headers"] is video_module.gc.VIDEO_HEADERS
    assert logger.debug.call_count == 1
    raw_args = logger.debug.call_args.args
    raw_kwargs = logger.debug.call_args.kwargs
    formatted_logs = "\n".join(str(call.args[0]).format(*call.args[1:]) for call in logger.mock_calls if call.args)
    assert 500 in raw_args
    assert jobid in raw_args
    assert raw_kwargs == {}
    assert "500" in formatted_logs
    assert jobid in formatted_logs
    for secret in (body_secret, url_secret, cookie_secret, authorization_secret, token_secret):
        assert secret not in repr(raw_args)
        assert secret not in repr(raw_kwargs)
        assert secret not in formatted_logs


@pytest.mark.parametrize(
    ("rt", "status_codes"),
    [
        pytest.param("1", [200], id="normal-rt"),
        pytest.param("", [403, 200], id="rt-fallback-retry"),
    ],
)
def test_video_progress_success_does_not_log_response_body(monkeypatch, rt, status_codes):
    logger = Mock()
    monkeypatch.setattr(video_module, "logger", logger)

    body_secret = "sentinel-video-success-body-secret"
    dtoken = "sentinel-video-success-token"
    jobid = "sentinel-video-success-jobid"
    responses = []
    for status_code in status_codes:
        response = Mock(
            status_code=status_code,
            text=f'{{"isPassed": true, "secret": "{body_secret}"}}',
            url=f"https://example.invalid/status?dtoken={dtoken}",
            headers={"Authorization": body_secret},
        )
        response.json.side_effect = lambda response=response: json.loads(response.text)
        responses.append(response)
    session = Mock()
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

    result = service.video_progress_log(
        session,
        {"clazzId": "clazz", "courseId": "course", "cpi": "cpi"},
        job,
        {},
        dtoken,
        10,
        1,
        headers={"Authorization": body_secret},
    )

    assert result == (True, 200)
    assert len(session.get.call_args_list) == len(status_codes)
    assert [response.json.call_count for response in responses if response.status_code == 200] == [1]
    raw_log_values = [value for call in logger.mock_calls for value in (*call.args, *call.kwargs.values())]
    raw_log_text = repr(raw_log_values)
    formatted_logs = "\n".join(str(call.args[0]).format(*call.args[1:]) for call in logger.mock_calls if call.args)
    assert str(status_codes[-1]) not in raw_log_text
    assert jobid not in raw_log_text
    for secret in (body_secret, dtoken):
        assert secret not in raw_log_text
        assert secret not in formatted_logs
