import logging
from typing import Any

from app.core.credential_crypto import (
    decrypt_dict_fields,
    encrypt_dict_fields,
)
from app.storage.factory import get_storage

logger = logging.getLogger(__name__)

# Fields treated as sensitive credentials. Values are encrypted before JSONB
# serialization and decrypted on read. Kept conservative — extend only with
# evidence that the field actually holds a secret.
_SENSITIVE_FIELDS: tuple[str, ...] = (
    "password",
    "user_password",
    "third_party_password",
)
# Nested containers that may hold credentials. We recurse one level into them.
_SENSITIVE_CONTAINERS: tuple[str, ...] = ("credentials",)


def _encrypt_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    """Encrypt top-level + ``payload.credentials.*`` sensitive keys.

    Fail-closed: if encryption raises, the offending field is DROPPED rather
    than persisted in plaintext. Other fields pass through.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        encrypted = encrypt_dict_fields(payload, _SENSITIVE_FIELDS)
    except Exception:
        logger.exception("task_store: encrypt top-level sensitive fields failed")
        encrypted = dict(payload)
        for field in _SENSITIVE_FIELDS:
            encrypted.pop(field, None)

    for container in _SENSITIVE_CONTAINERS:
        nested = encrypted.get(container)
        if isinstance(nested, dict):
            try:
                encrypted[container] = encrypt_dict_fields(nested, _SENSITIVE_FIELDS)
            except Exception:
                logger.exception("task_store: encrypt nested container=%s failed", container)
                cleaned = dict(nested)
                for field in _SENSITIVE_FIELDS:
                    cleaned.pop(field, None)
                encrypted[container] = cleaned
    return encrypted


def _decrypt_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    """Decrypt top-level + ``payload.credentials.*`` sensitive keys.

    Legacy (non-``fernet:``-prefixed) values pass through unchanged.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        decrypted = decrypt_dict_fields(payload, _SENSITIVE_FIELDS)
    except Exception:
        logger.exception("task_store: decrypt top-level sensitive fields failed")
        decrypted = dict(payload)

    for container in _SENSITIVE_CONTAINERS:
        nested = decrypted.get(container)
        if isinstance(nested, dict):
            try:
                decrypted[container] = decrypt_dict_fields(nested, _SENSITIVE_FIELDS)
            except Exception:
                logger.exception("task_store: decrypt nested container=%s failed", container)
    return decrypted


class TaskStore:
    def ensure_tables(self) -> None:
        get_storage().tasks.ensure_tables()

    def upsert_task(self, task_kind: str, task_state_public: dict[str, Any]) -> None:
        if not task_kind or not isinstance(task_state_public, dict):
            return
        get_storage().tasks.upsert_task(task_kind, _encrypt_sensitive(task_state_public))

    def get_task(
        self,
        task_kind: str,
        task_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        item = get_storage().tasks.get_task(task_kind, task_id, user_id)
        if item is None:
            return None
        return _decrypt_sensitive(item)

    def list_tasks(
        self,
        task_kind: str,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return [_decrypt_sensitive(item) for item in get_storage().tasks.list_tasks(task_kind, user_id, limit)]

    def append_history(
        self,
        history_kind: str,
        user_id: str,
        record: dict[str, Any],
        max_records: int = 500,
    ) -> None:
        if not history_kind or not user_id or not isinstance(record, dict):
            return
        get_storage().tasks.append_history(history_kind, user_id, _encrypt_sensitive(record), max_records)

    def list_history(
        self,
        history_kind: str,
        user_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return [_decrypt_sensitive(item) for item in get_storage().tasks.list_history(history_kind, user_id, limit)]


task_store = TaskStore()
