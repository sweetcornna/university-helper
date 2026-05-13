import pytest
from unittest.mock import patch
from app.config import Settings

# SECRET_KEY is now length-validated (>= 16 chars). Use a placeholder that
# passes validation in tests focused on the rest of the config surface.
_TEST_SECRET = "x" * 32


def test_settings_defaults():
    with patch.dict('os.environ', {'SECRET_KEY': _TEST_SECRET, 'CORS_ORIGINS': '["*"]'}):
        settings = Settings()
        assert settings.MAIN_DB_HOST == "localhost"
        assert settings.MAIN_DB_PORT == 5432
        assert settings.ALGORITHM == "HS256"


def test_settings_missing_secret_key():
    from pydantic_core import ValidationError
    with patch.dict('os.environ', {
        'MAIN_DB_USER': 'u',
        'MAIN_DB_PASSWORD': 'p',
    }, clear=True):
        with pytest.raises(ValidationError):
            Settings()


def test_settings_short_secret_key_rejected():
    from pydantic_core import ValidationError
    with patch.dict('os.environ', {
        'SECRET_KEY': 'too-short',
        'CORS_ORIGINS': '["*"]',
        'MAIN_DB_USER': 'u',
        'MAIN_DB_PASSWORD': 'p',
    }, clear=True):
        with pytest.raises(ValidationError):
            Settings()


def test_settings_missing_cors():
    with patch.dict('os.environ', {
        'SECRET_KEY': _TEST_SECRET,
        'MAIN_DB_USER': 'u',
        'MAIN_DB_PASSWORD': 'p',
    }, clear=True):
        with pytest.raises(ValueError, match="CORS_ORIGINS must be set"):
            Settings()


def test_settings_custom_values():
    with patch.dict('os.environ', {
        'SECRET_KEY': _TEST_SECRET,
        'CORS_ORIGINS': '["*"]',
        'MAIN_DB_HOST': 'custom',
        'MAIN_DB_PORT': '3306'
    }):
        settings = Settings()
        assert settings.MAIN_DB_HOST == "custom"
        assert settings.MAIN_DB_PORT == 3306
