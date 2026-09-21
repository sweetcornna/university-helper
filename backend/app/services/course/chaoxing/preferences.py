"""Per-user Chaoxing task preferences.

Persisted in the shared task store — one row per platform user, exactly like the
Chaoxing session in ``cookies.save_session`` — so a one-click run does not need
the answer-bank settings retyped. ``tiku_token`` and ``ai_key`` are credentials:
they are listed in ``task_store._SENSITIVE_FIELDS`` and therefore Fernet-encrypted
at rest (and DROPPED rather than written in plaintext if encryption fails).
"""

from typing import Any

from loguru import logger

from ..task_store import task_store

# One record per platform user, keyed by the user id, under its own task kind.
CHAOXING_PREFS_KIND = "chaoxing_task_prefs"

# Echoed by the API in place of a stored secret. A PUT carrying it back means
# "leave the stored value alone" — the SPA never receives the real secret.
SECRET_MASK = "***"

# Must stay in sync with task_store._SENSITIVE_FIELDS so both are encrypted.
TIKU_TOKEN_FIELD = "tiku_token"
AI_KEY_FIELD = "ai_key"
SECRET_FIELDS: tuple[str, ...] = (TIKU_TOKEN_FIELD, AI_KEY_FIELD)

# The tiku/speed/concurrency settings the SPA already sends to /course/start.
PREFERENCE_FIELDS: tuple[str, ...] = (
    "speed",
    "concurrency",
    "unopened_strategy",
    "tiku_provider",
    TIKU_TOKEN_FIELD,
    "ai_endpoint",
    AI_KEY_FIELD,
    "ai_model",
    "coverage_threshold",
    "correct_options",
    "wrong_options",
    "submit_mode",
    "notify_service",
    "notify_url",
)


def _mask_user(user_id) -> str:
    """Mask a platform user id for logging."""
    uid = str(user_id or "")
    return f"{uid[:4]}***" if len(uid) > 4 else "***"


def _normalize_user_id(user_id) -> str:
    return str(user_id or "").strip()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _split_csv(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value or "").split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def load_preferences(user_id) -> dict[str, Any] | None:
    """Return the stored preferences for ``user_id`` with secrets in PLAINTEXT.

    Returns None when nothing is stored. Callers that hand the result to a
    client MUST project it through :func:`masked_preferences` first.
    """
    uid = _normalize_user_id(user_id)
    if not uid:
        return None
    try:
        # user_id is passed so the store can only ever return this user's row.
        record = task_store.get_task(CHAOXING_PREFS_KIND, uid, uid)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("读取超星任务偏好失败 user={} err={}", _mask_user(uid), exc)
        return None
    if not record:
        return None
    return {field: record[field] for field in PREFERENCE_FIELDS if field in record}


def save_preferences(user_id, updates: dict[str, Any]) -> bool:
    """Merge ``updates`` over the stored preferences and persist them.

    Merge rule, applied to every field: a field absent from ``updates`` (or sent
    as null) keeps its stored value; a field that is present replaces it. Secrets
    additionally treat :data:`SECRET_MASK` as "absent", because that is what a
    read handed the client, while an empty string CLEARS the stored secret.

    Returns False when the record could not be persisted.
    """
    uid = _normalize_user_id(user_id)
    if not uid or not isinstance(updates, dict):
        return False

    merged = load_preferences(uid) or {}
    for field in PREFERENCE_FIELDS:
        value = updates.get(field)
        if value is None:
            continue
        if field in SECRET_FIELDS and _text(value) == SECRET_MASK:
            continue
        merged[field] = value

    record: dict[str, Any] = {
        # One preferences row per platform user, so the row key is the user.
        "task_id": uid,
        "user_id": uid,
        "status": "active",
        "message": "",
        **merged,
    }
    try:
        task_store.upsert_task(CHAOXING_PREFS_KIND, record)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("保存超星任务偏好失败 user={} err={}", _mask_user(uid), exc)
        return False
    return True


def masked_preferences(prefs: dict[str, Any]) -> dict[str, Any]:
    """Client-facing projection: secrets replaced by the mask, never the value.

    Each secret also gets a ``has_*`` flag so the SPA can render "已保存" without
    ever receiving the secret itself.
    """
    public = {field: prefs.get(field) for field in PREFERENCE_FIELDS}
    public[TIKU_TOKEN_FIELD] = SECRET_MASK if _text(prefs.get(TIKU_TOKEN_FIELD)) else ""
    public[AI_KEY_FIELD] = SECRET_MASK if _text(prefs.get(AI_KEY_FIELD)) else ""
    public["has_tiku_token"] = bool(_text(prefs.get(TIKU_TOKEN_FIELD)))
    public["has_ai_key"] = bool(_text(prefs.get(AI_KEY_FIELD)))
    return public


def has_answer_bank(prefs: dict[str, Any] | None) -> bool:
    """True when the stored credentials can actually answer a quiz.

    Either a tiku token, or an AI key complete with an endpoint AND a model —
    the AI provider self-disables when any of the three is missing, which is the
    silent "watched every video, answered nothing" failure this flag warns about.
    """
    if not prefs:
        return False
    if _text(prefs.get(TIKU_TOKEN_FIELD)):
        return True
    return bool(_text(prefs.get(AI_KEY_FIELD)) and _text(prefs.get("ai_endpoint")) and _text(prefs.get("ai_model")))


def build_tiku_config(prefs: dict[str, Any]) -> dict[str, Any]:
    """Build the ``/course/start`` ``tiku_config`` block from stored preferences.

    Mirrors the payload the SPA posts today so a one-click run reaches
    ``normalize_tiku_config`` with exactly the same keys as a manual run.
    """
    token = _text(prefs.get(TIKU_TOKEN_FIELD))
    ai_key = _text(prefs.get(AI_KEY_FIELD))
    return {
        "provider": ",".join(_split_csv(prefs.get("tiku_provider"))),
        "token": token,
        "endpoint": _text(prefs.get("ai_endpoint")),
        "key": ai_key,
        "model": _text(prefs.get("ai_model")),
        # SiliconFlow reuses the AI key, falling back to the tiku token.
        "siliconflow_key": ai_key or token,
        "coverage_threshold": prefs.get("coverage_threshold"),
        "judge_mapping": {
            "correct": _split_csv(prefs.get("correct_options")),
            "wrong": _split_csv(prefs.get("wrong_options")),
        },
        "submit_mode": _text(prefs.get("submit_mode")),
    }


def build_notify_config(prefs: dict[str, Any]) -> dict[str, Any]:
    """Build the ``/course/start`` ``notify_config`` block, or {} when incomplete."""
    service = _text(prefs.get("notify_service"))
    url = _text(prefs.get("notify_url"))
    if not service or not url:
        return {}
    return {"service": service, "url": url}
