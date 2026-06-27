from unittest.mock import patch

import pytest

from app.config import LOCAL_USER_ID, Settings

_TEST_SECRET = "x" * 32
# _BASE_ENV must include non-empty DB creds so the postgres-creds validator
# does not fire in tests that are not exercising that specific path.
_BASE_ENV = {
    "SECRET_KEY": _TEST_SECRET,
    "CORS_ORIGINS": '["*"]',
    "MAIN_DB_USER": "test_user",
    "MAIN_DB_PASSWORD": "test_password",
}


def test_profile_and_storage_defaults_are_server_postgres():
    with patch.dict("os.environ", _BASE_ENV, clear=True):
        s = Settings()
        assert s.PROFILE == "server"
        assert s.STORAGE_BACKEND == "postgres"
        assert s.SQLITE_PATH == ""


def test_profile_and_storage_read_from_env():
    env = {**_BASE_ENV, "PROFILE": "local", "STORAGE_BACKEND": "sqlite", "SQLITE_PATH": "/tmp/uh.db"}
    with patch.dict("os.environ", env, clear=True):
        s = Settings()
        assert s.PROFILE == "local"
        assert s.STORAGE_BACKEND == "sqlite"
        assert s.SQLITE_PATH == "/tmp/uh.db"


def test_local_user_id_constant():
    assert LOCAL_USER_ID == "local"


# --- Reconciliation tests: MAIN_DB_USER/MAIN_DB_PASSWORD are optional when
# STORAGE_BACKEND != "postgres", but required (non-empty) for postgres. ---


def test_postgres_empty_creds_raises():
    from pydantic_core import ValidationError

    env = {
        "SECRET_KEY": _TEST_SECRET,
        "CORS_ORIGINS": '["*"]',
        "STORAGE_BACKEND": "postgres",
        "MAIN_DB_USER": "",
        "MAIN_DB_PASSWORD": "",
    }
    with patch.dict("os.environ", env, clear=True):
        with pytest.raises(ValidationError, match="MAIN_DB_USER and MAIN_DB_PASSWORD"):
            Settings()


def test_sqlite_empty_creds_ok():
    env = {
        "SECRET_KEY": _TEST_SECRET,
        "CORS_ORIGINS": '["*"]',
        "STORAGE_BACKEND": "sqlite",
        "MAIN_DB_USER": "",
        "MAIN_DB_PASSWORD": "",
    }
    with patch.dict("os.environ", env, clear=True):
        s = Settings()
        assert s.STORAGE_BACKEND == "sqlite"
        assert s.MAIN_DB_USER == ""
        assert s.MAIN_DB_PASSWORD == ""
