"""At-rest encryption for third-party credentials.

Reads a symmetric Fernet key from env var ``CREDENTIAL_ENCRYPTION_KEY``.

- In production (``ENV=production``), a missing / invalid key raises at startup.
- In development, a missing key falls back to a loudly-logged no-op cipher
  so that local dev and tests without a configured key don't crash — but the
  warning makes it obvious that plaintext is being stored.

Ciphertext values are stored with a ``fernet:`` prefix so we can distinguish
them from legacy plaintext rows that may already exist in the DB.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Iterable, Mapping

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIX = "fernet:"
_ENV_VAR = "CREDENTIAL_ENCRYPTION_KEY"


class CredentialCryptoError(RuntimeError):
    """Raised when encryption cannot be initialized in a context requiring it."""


class _NoopCipher:
    """Dev fallback: returns input unchanged. Never used in production."""

    def encrypt(self, plain: str) -> str:
        return plain

    def decrypt(self, value: str) -> str:
        return value


class _FernetCipher:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plain: str) -> str:
        token = self._fernet.encrypt(plain.encode("utf-8")).decode("ascii")
        return f"{_PREFIX}{token}"

    def decrypt(self, value: str) -> str:
        if not value.startswith(_PREFIX):
            return value
        token = value[len(_PREFIX):].encode("ascii")
        return self._fernet.decrypt(token).decode("utf-8")


_cipher_lock = threading.Lock()
_cipher: _FernetCipher | _NoopCipher | None = None


def _is_production() -> bool:
    env = (os.getenv("ENV") or os.getenv("APP_ENV") or "").strip().lower()
    return env in ("prod", "production")


def _build_cipher() -> _FernetCipher | _NoopCipher:
    raw = os.getenv(_ENV_VAR)
    if not raw:
        if _is_production():
            raise CredentialCryptoError(
                f"{_ENV_VAR} is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        logger.warning(
            "!!! %s not set — using NO-OP cipher. Third-party credentials will be "
            "stored in PLAINTEXT. Set %s before deploying. !!!",
            _ENV_VAR,
            _ENV_VAR,
        )
        return _NoopCipher()

    try:
        return _FernetCipher(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        if _is_production():
            raise CredentialCryptoError(
                f"{_ENV_VAR} is invalid: {exc}. Expected a urlsafe-base64 Fernet key."
            ) from exc
        logger.warning(
            "!!! %s is invalid (%s) — using NO-OP cipher. Credentials will be "
            "stored in PLAINTEXT. !!!",
            _ENV_VAR,
            exc,
        )
        return _NoopCipher()


def init_cipher() -> None:
    """Eagerly build the cipher. Raises in production if the key is missing.

    Callers (lifespan) use this to fail fast at startup instead of waiting
    for the first credential operation.
    """
    _get_cipher()


def _get_cipher() -> _FernetCipher | _NoopCipher:
    global _cipher
    if _cipher is not None:
        return _cipher
    with _cipher_lock:
        if _cipher is None:
            _cipher = _build_cipher()
    return _cipher


def _reset_for_tests() -> None:
    """Force rebuild of cipher on next access. Intended for unit tests only."""
    global _cipher
    with _cipher_lock:
        _cipher = None


def encrypt_str(plain: str) -> str:
    """Encrypt a string. Returns a ``fernet:``-prefixed token.

    Non-string / empty values are returned unchanged so callers can pass
    through missing fields safely.
    """
    if not isinstance(plain, str) or not plain:
        return plain
    if plain.startswith(_PREFIX):
        # Already encrypted — don't double-encrypt.
        return plain
    return _get_cipher().encrypt(plain)


def decrypt_str(value: str) -> str:
    """Decrypt a ``fernet:``-prefixed string. Passes through legacy plaintext."""
    if not isinstance(value, str) or not value:
        return value
    if not value.startswith(_PREFIX):
        return value
    try:
        return _get_cipher().decrypt(value)
    except InvalidToken as exc:
        raise CredentialCryptoError("Failed to decrypt: wrong key or corrupt token") from exc


def encrypt_dict_fields(data: Mapping[str, object], fields: Iterable[str]) -> dict:
    """Return a shallow copy of ``data`` with named fields encrypted.

    Non-string values at a named field are left untouched.
    """
    if not isinstance(data, Mapping):
        return dict(data) if data else {}
    out = dict(data)
    for field in fields:
        value = out.get(field)
        if isinstance(value, str) and value:
            out[field] = encrypt_str(value)
    return out


def decrypt_dict_fields(data: Mapping[str, object], fields: Iterable[str]) -> dict:
    """Return a shallow copy of ``data`` with named fields decrypted.

    Fields that are not ``fernet:``-prefixed are left unchanged (legacy rows).
    """
    if not isinstance(data, Mapping):
        return dict(data) if data else {}
    out = dict(data)
    for field in fields:
        value = out.get(field)
        if isinstance(value, str) and value.startswith(_PREFIX):
            try:
                out[field] = decrypt_str(value)
            except CredentialCryptoError:
                logger.exception("decrypt_dict_fields: failed to decrypt field=%s", field)
                # Leave ciphertext in place rather than leak wrong data.
    return out
