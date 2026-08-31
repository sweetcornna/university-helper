from unittest.mock import Mock

import app.services.course.chaoxing.media_service as media_module
from app.services.course.chaoxing.media_service import ChaoxingMediaService


def _format_log_calls(calls):
    return "\n".join(str(call.args[0]).format(*call.args[1:]) for call in calls if call.args)


def test_refreshed_media_token_is_used_without_logging_secret(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(media_module, "logger", logger)
    monkeypatch.setattr(media_module, "tqdm", lambda *args, **kwargs: Mock())
    monkeypatch.setattr(media_module.time, "sleep", lambda *args, **kwargs: None)

    initial_token = "sentinel-initial-token"
    refreshed_token = "sentinel-refreshed-token"
    cookie = "sentinel-cookie"
    authorization = "sentinel-authorization"
    custom_header = "sentinel-custom-header"
    jobid = "sentinel-jobid"

    status_response = Mock()
    status_response.json.return_value = {
        "status": "success",
        "dtoken": initial_token,
        "crc": "crc",
        "key": "key",
        "duration": 10,
    }
    initial_progress_response = Mock(status_code=200)
    initial_progress_response.json.return_value = {"isPassed": False}
    forbidden_response = Mock(status_code=403)
    passed_response = Mock(status_code=200)
    passed_response.json.return_value = {"isPassed": True}

    session = Mock(headers={"Cookie": cookie, "Authorization": authorization, "X-Custom": custom_header})
    session.get.side_effect = [status_response, initial_progress_response, forbidden_response, passed_response]
    session_manager = Mock()
    session_manager.get_session.return_value = session
    service = ChaoxingMediaService(
        get_fid_func=lambda: "fid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
        session_manager=session_manager,
    )
    service._recover_after_forbidden = Mock(return_value={"dtoken": refreshed_token, "duration": 42, "playTime": 42})
    job = {
        "name": "media-job",
        "jobid": jobid,
        "objectid": "objectid",
        "otherinfo": "nodeId_x",
        "playTime": 10_000,
        "property": {
            "akid": "akid",
            "userid": "userid",
            "isdrag": "0",
            "rt": "1",
            "dtype": "Video",
        },
    }

    result = service.study_video(
        {"clazzId": "clazz", "courseId": "course", "cpi": "cpi"},
        job,
        {},
    )

    assert result is True
    service._recover_after_forbidden.assert_called_once()
    assert len(session.get.call_args_list) == 4
    initial_progress_call = session.get.call_args_list[1]
    refreshed_progress_call = session.get.call_args_list[3]
    assert initial_progress_call.args[0].endswith(f"/{initial_token}")
    assert refreshed_progress_call.args[0].endswith(f"/{refreshed_token}")
    assert refreshed_progress_call.kwargs["params"]["jobid"] == jobid
    assert refreshed_progress_call.kwargs["params"]["duration"] == "42"
    assert refreshed_progress_call.kwargs["params"]["playingTime"] == "42"

    raw_log_values = [value for call in logger.mock_calls for value in (*call.args, *call.kwargs.values())]
    raw_log_text = repr(raw_log_values)
    formatted_logs = _format_log_calls(logger.mock_calls)
    assert 42 in raw_log_values
    assert "duration=42" in formatted_logs
    assert "play time=42" in formatted_logs
    for secret in (initial_token, refreshed_token, cookie, authorization, custom_header):
        assert secret not in raw_log_text
        assert secret not in formatted_logs
    assert "https://" not in formatted_logs
    assert "Cookie" not in formatted_logs
    assert "Authorization" not in formatted_logs


def test_media_status_refresh_redacts_non_200_response_context(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(media_module, "logger", logger)

    body_secret = "sentinel-media-refresh-body"
    url_secret = "sentinel-media-refresh-url"
    cookie_secret = "sentinel-media-refresh-cookie"
    authorization_secret = "sentinel-media-refresh-authorization"
    token_secret = "sentinel-media-refresh-token"
    jobid = "sentinel-media-refresh-jobid"
    response = Mock(
        status_code=500,
        text=f"failure body: {body_secret} token={token_secret}",
        url=f"https://example.invalid/status?secret={url_secret}",
        headers={"Cookie": cookie_secret, "Authorization": authorization_secret},
    )
    session = Mock()
    session.get.return_value = response
    service = ChaoxingMediaService(
        get_fid_func=lambda: "fid",
        rate_limiter=Mock(),
        video_log_limiter=Mock(),
    )

    result = service._refresh_video_status(session, {"objectid": "objectid", "jobid": jobid}, "Video")

    assert result is None
    assert session.get.call_count == 1
    assert session.get.call_args.kwargs["timeout"] == 8
    assert session.get.call_args.kwargs["headers"] is media_module.gc.VIDEO_HEADERS
    assert logger.debug.call_count == 1
    raw_args = logger.debug.call_args.args
    raw_kwargs = logger.debug.call_args.kwargs
    formatted_logs = _format_log_calls(logger.mock_calls)
    assert 500 in raw_args
    assert jobid in raw_args
    assert raw_kwargs == {}
    assert "500" in formatted_logs
    assert jobid in formatted_logs
    for secret in (body_secret, url_secret, cookie_secret, authorization_secret, token_secret):
        assert secret not in repr(raw_args)
        assert secret not in repr(raw_kwargs)
        assert secret not in formatted_logs
