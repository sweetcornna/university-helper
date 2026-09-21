import json
from unittest.mock import Mock

import pytest

from app.services.course.chaoxing import cookies


@pytest.fixture
def cookies_file(tmp_path, monkeypatch):
    path = tmp_path / "cookies.json"
    monkeypatch.setattr(cookies, "COOKIES_FILE", path)
    return path


def test_save_cookies(cookies_file):
    mock_session = Mock()
    mock_session.cookies.get_dict.return_value = {"key": "value"}

    cookies.save_cookies(mock_session)

    assert cookies_file.exists()
    data = json.loads(cookies_file.read_text())
    assert data == {"key": "value"}


def test_use_cookies_exists(cookies_file):
    cookies_file.write_text(json.dumps({"key": "value"}))

    result = cookies.use_cookies()

    assert result == {"key": "value"}


def test_use_cookies_not_exists(cookies_file):
    result = cookies.use_cookies()
    assert result == {}
