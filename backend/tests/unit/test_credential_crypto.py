"""Unit tests for app.core.credential_crypto — no DB required."""

from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def crypto_with_key(monkeypatch, tmp_path):
    """Fresh module bound to a real Fernet key."""
    monkeypatch.chdir(tmp_path)
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)
    monkeypatch.delenv("ENV", raising=False)

    import app.core.credential_crypto as cc

    importlib.reload(cc)
    cc._reset_for_tests()
    yield cc
    cc._reset_for_tests()


@pytest.fixture
def crypto_dev_no_key(monkeypatch, tmp_path):
    """Fresh module with no key configured and ENV!=production (dev fallback)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ENV", raising=False)

    import app.core.credential_crypto as cc

    importlib.reload(cc)
    cc._reset_for_tests()
    yield cc
    cc._reset_for_tests()


def test_round_trip_encrypts_and_decrypts(crypto_with_key):
    cc = crypto_with_key
    plain = "super-secret-chaoxing-pw"
    token = cc.encrypt_str(plain)

    assert token.startswith("fernet:")
    assert plain not in token
    assert cc.decrypt_str(token) == plain


def test_empty_and_non_string_passthrough(crypto_with_key):
    cc = crypto_with_key
    assert cc.encrypt_str("") == ""
    assert cc.encrypt_str(None) is None  # type: ignore[arg-type]
    assert cc.decrypt_str("") == ""
    assert cc.decrypt_str(None) is None  # type: ignore[arg-type]


def test_plaintext_passthrough_on_decrypt(crypto_with_key):
    """Legacy rows without the prefix must be returned unchanged."""
    cc = crypto_with_key
    assert cc.decrypt_str("legacy-plaintext-pw") == "legacy-plaintext-pw"


def test_double_encrypt_is_idempotent(crypto_with_key):
    cc = crypto_with_key
    token = cc.encrypt_str("hello")
    assert cc.encrypt_str(token) == token


def test_wrong_key_raises(crypto_with_key, monkeypatch):
    cc = crypto_with_key
    token = cc.encrypt_str("hello")

    # Swap in a different key and reload the module's cipher.
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    cc._reset_for_tests()

    with pytest.raises(cc.CredentialCryptoError):
        cc.decrypt_str(token)


def test_encrypt_dict_fields_round_trip(crypto_with_key):
    cc = crypto_with_key
    data = {
        "username": "alice",
        "password": "p@ss",
        "user_password": "other-pw",
        "third_party_password": "third-pw",
        "irrelevant": 42,
    }
    fields = ("password", "user_password", "third_party_password")
    enc = cc.encrypt_dict_fields(data, fields)

    for f in fields:
        assert enc[f].startswith("fernet:")
        assert enc[f] != data[f]
    assert enc["username"] == "alice"
    assert enc["irrelevant"] == 42

    dec = cc.decrypt_dict_fields(enc, fields)
    assert dec == data


def test_decrypt_dict_fields_skips_plaintext(crypto_with_key):
    cc = crypto_with_key
    data = {"password": "still-plaintext", "username": "bob"}
    dec = cc.decrypt_dict_fields(data, ("password",))
    assert dec["password"] == "still-plaintext"
    assert dec["username"] == "bob"


def test_encrypt_dict_fields_ignores_missing_and_non_string(crypto_with_key):
    cc = crypto_with_key
    data = {"password": None, "user_password": 123, "other": "x"}
    enc = cc.encrypt_dict_fields(data, ("password", "user_password", "missing"))
    assert enc["password"] is None
    assert enc["user_password"] == 123
    assert "missing" not in enc
    assert enc["other"] == "x"


def test_dev_noop_fallback_when_key_missing(crypto_dev_no_key, caplog):
    """In dev, a missing key must NOT crash — but must warn loudly."""
    cc = crypto_dev_no_key
    with caplog.at_level("WARNING"):
        out = cc.encrypt_str("plain")
    # No-op cipher returns input unchanged (no prefix).
    assert out == "plain"
    assert any("NO-OP cipher" in rec.message for rec in caplog.records)


def test_production_without_key_raises(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ENV", "production")

    import app.core.credential_crypto as cc

    importlib.reload(cc)
    cc._reset_for_tests()
    try:
        with pytest.raises(cc.CredentialCryptoError):
            cc.encrypt_str("anything")
    finally:
        cc._reset_for_tests()


def test_production_from_env_file_without_key_raises(monkeypatch, tmp_path):
    """A dotenv-only production profile must fail closed like Settings does."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ENV=production\n", encoding="utf-8")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    import app.core.credential_crypto as cc

    importlib.reload(cc)
    cc._reset_for_tests()
    try:
        with pytest.raises(cc.CredentialCryptoError, match="CREDENTIAL_ENCRYPTION_KEY is not set"):
            cc.init_cipher()
    finally:
        cc._reset_for_tests()
