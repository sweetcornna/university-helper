"""Per-user Chaoxing task preferences.

Covers the round trip, that the answer-bank credentials are encrypted at rest and
masked on read, the three-way mask / omit / empty-string update semantics, that
one user can never read or overwrite another's record, and that /course/start
still behaves exactly as before for a full payload while a minimal payload picks
up the stored defaults. Storage is monkeypatched — no live DB.
"""

import json
import types

import pytest
from fastapi.testclient import TestClient

import app.services.course.task_store as task_store_mod
from app.services.course.chaoxing.preferences import (
    CHAOXING_PREFS_KIND,
    SECRET_MASK,
    build_notify_config,
    build_tiku_config,
    has_answer_bank,
    load_preferences,
    masked_preferences,
    save_preferences,
)
from tests.conftest import build_app

FULL_PREFS = {
    "speed": 2.0,
    "concurrency": 8,
    "unopened_strategy": "continue",
    "tiku_provider": ["TikuYanxi", "TikuGo"],
    "tiku_token": "yanxi-secret-token",
    "ai_endpoint": "https://api.example.com/v1/chat/completions",
    "ai_key": "sk-super-secret-key",
    "ai_model": "gpt-4o-mini",
    "coverage_threshold": 0.75,
    "correct_options": "对,正确",
    "wrong_options": "错,错误",
    "submit_mode": "save",
    "notify_service": "bark",
    "notify_url": "https://push.example.com/token",
}


class FakeTaskBackend:
    """In-memory stand-in for the storage adapter behind TaskStore."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def ensure_tables(self) -> None:
        pass

    def upsert_task(self, task_kind, payload):
        self.rows[(task_kind, str(payload.get("task_id")))] = json.loads(json.dumps(payload, default=str))

    def get_task(self, task_kind, task_id, user_id=None):
        row = self.rows.get((task_kind, str(task_id)))
        if row is None:
            return None
        if user_id and str(row.get("user_id")) != str(user_id):
            return None
        return dict(row)

    def list_tasks(self, task_kind, user_id=None, limit=50):
        return []

    def append_history(self, history_kind, user_id, record, max_records=500):
        pass

    def list_history(self, history_kind, user_id=None, limit=500):
        return []

    def raw(self, user_id):
        """The row exactly as it hit storage — i.e. still encrypted."""
        return self.rows.get((CHAOXING_PREFS_KIND, str(user_id)))


@pytest.fixture
def store(monkeypatch):
    backend = FakeTaskBackend()
    monkeypatch.setattr(task_store_mod, "get_storage", lambda: types.SimpleNamespace(tasks=backend))
    return backend


@pytest.fixture
def real_cipher(monkeypatch):
    """Enable REAL Fernet encryption so a missing-encrypt regression can't slip by."""
    from cryptography.fernet import Fernet

    from app.core import credential_crypto

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    credential_crypto._reset_for_tests()
    yield
    credential_crypto._reset_for_tests()


# ---------------------------------------------------------------------------
# Round trip + isolation
# ---------------------------------------------------------------------------


def test_preferences_round_trip(store):
    assert load_preferences("user-1") is None

    assert save_preferences("user-1", FULL_PREFS) is True

    assert load_preferences("user-1") == FULL_PREFS


def test_preferences_are_isolated_per_platform_user(store):
    save_preferences("user-1", FULL_PREFS)
    save_preferences("user-2", {"tiku_token": "other-user-token", "speed": 1.0})

    assert load_preferences("user-1")["tiku_token"] == "yanxi-secret-token"
    assert load_preferences("user-2")["tiku_token"] == "other-user-token"
    # user-2's write left user-1's record completely untouched.
    assert load_preferences("user-1") == FULL_PREFS
    # ...and the rows are keyed apart, not merged.
    assert store.raw("user-1") is not store.raw("user-2")


def test_saving_without_a_user_id_persists_nothing(store):
    assert save_preferences("", FULL_PREFS) is False
    assert store.rows == {}


# ---------------------------------------------------------------------------
# Secrets: encrypted at rest, masked on read
# ---------------------------------------------------------------------------


def test_secrets_are_encrypted_at_rest(store, real_cipher):
    save_preferences("user-1", FULL_PREFS)

    row = store.raw("user-1")
    assert row["tiku_token"].startswith("fernet:")
    assert row["ai_key"].startswith("fernet:")
    raw_text = json.dumps(row)
    assert "yanxi-secret-token" not in raw_text
    assert "sk-super-secret-key" not in raw_text
    # Non-secret settings stay readable, and the secrets still round-trip.
    assert row["ai_model"] == "gpt-4o-mini"
    assert load_preferences("user-1")["ai_key"] == "sk-super-secret-key"


def test_encryption_failure_drops_secrets_instead_of_persisting_plaintext(store, monkeypatch):
    def _boom(payload, fields):
        raise RuntimeError("cipher unavailable")

    monkeypatch.setattr(task_store_mod, "encrypt_dict_fields", _boom)

    save_preferences("user-1", FULL_PREFS)

    row = store.raw("user-1")
    assert "tiku_token" not in row
    assert "ai_key" not in row
    assert "yanxi-secret-token" not in json.dumps(row)
    assert "sk-super-secret-key" not in json.dumps(row)
    # The non-secret settings survive, so the user only loses the credentials.
    assert row["ai_model"] == "gpt-4o-mini"


def test_masked_preferences_never_expose_a_secret(store):
    save_preferences("user-1", FULL_PREFS)

    public = masked_preferences(load_preferences("user-1"))

    assert public["tiku_token"] == SECRET_MASK
    assert public["ai_key"] == SECRET_MASK
    assert public["has_tiku_token"] is True
    assert public["has_ai_key"] is True
    assert "yanxi-secret-token" not in json.dumps(public)
    assert "sk-super-secret-key" not in json.dumps(public)
    # Non-secret settings come back verbatim so the SPA can rehydrate its form.
    assert public["speed"] == 2.0
    assert public["tiku_provider"] == ["TikuYanxi", "TikuGo"]


def test_masked_preferences_report_absent_secrets_as_empty(store):
    save_preferences("user-1", {"speed": 1.5})

    public = masked_preferences(load_preferences("user-1"))

    assert public["tiku_token"] == ""
    assert public["ai_key"] == ""
    assert public["has_tiku_token"] is False
    assert public["has_ai_key"] is False


# ---------------------------------------------------------------------------
# Three-way update semantics: mask / omit / empty string
# ---------------------------------------------------------------------------


def test_mask_leaves_the_stored_secret_unchanged(store):
    save_preferences("user-1", FULL_PREFS)

    save_preferences("user-1", {"tiku_token": SECRET_MASK, "ai_key": SECRET_MASK, "speed": 1.25})

    stored = load_preferences("user-1")
    assert stored["tiku_token"] == "yanxi-secret-token"
    assert stored["ai_key"] == "sk-super-secret-key"
    assert stored["speed"] == 1.25  # the non-secret edit still landed


def test_omitted_secret_leaves_the_stored_secret_unchanged(store):
    save_preferences("user-1", FULL_PREFS)

    save_preferences("user-1", {"speed": 1.25})

    stored = load_preferences("user-1")
    assert stored["tiku_token"] == "yanxi-secret-token"
    assert stored["ai_key"] == "sk-super-secret-key"


def test_empty_string_clears_the_stored_secret(store):
    save_preferences("user-1", FULL_PREFS)

    save_preferences("user-1", {"tiku_token": "", "ai_key": ""})

    stored = load_preferences("user-1")
    assert stored["tiku_token"] == ""
    assert stored["ai_key"] == ""
    assert has_answer_bank(stored) is False


def test_a_new_secret_replaces_the_stored_one(store):
    save_preferences("user-1", FULL_PREFS)

    save_preferences("user-1", {"tiku_token": "fresh-token"})

    assert load_preferences("user-1")["tiku_token"] == "fresh-token"


# ---------------------------------------------------------------------------
# has_answer_bank
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prefs,expected",
    [
        (None, False),
        ({}, False),
        ({"tiku_token": "t"}, True),
        ({"ai_key": "k"}, False),  # no endpoint / model -> AI provider self-disables
        ({"ai_key": "k", "ai_endpoint": "https://x/v1"}, False),
        ({"ai_key": "k", "ai_endpoint": "https://x/v1", "ai_model": "m"}, True),
        ({"ai_endpoint": "https://x/v1", "ai_model": "m"}, False),
        ({"tiku_token": "   ", "ai_key": ""}, False),
    ],
)
def test_has_answer_bank(prefs, expected):
    assert has_answer_bank(prefs) is expected


# ---------------------------------------------------------------------------
# /course/start payload building
# ---------------------------------------------------------------------------


def test_build_tiku_config_matches_the_spa_payload():
    config = build_tiku_config(FULL_PREFS)

    assert config["provider"] == "TikuYanxi,TikuGo"
    assert config["token"] == "yanxi-secret-token"
    assert config["key"] == "sk-super-secret-key"
    assert config["siliconflow_key"] == "sk-super-secret-key"
    assert config["model"] == "gpt-4o-mini"
    assert config["coverage_threshold"] == 0.75
    assert config["judge_mapping"] == {"correct": ["对", "正确"], "wrong": ["错", "错误"]}
    assert config["submit_mode"] == "save"


def test_build_notify_config_requires_both_service_and_url():
    assert build_notify_config(FULL_PREFS) == {"service": "bark", "url": "https://push.example.com/token"}
    assert build_notify_config({"notify_service": "bark"}) == {}
    assert build_notify_config({"notify_url": "https://push.example.com/token"}) == {}


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


class RecordingLearningManager:
    def __init__(self):
        self.payloads = []

    def start_task(self, user_id, payload):
        self.payloads.append(payload)
        return "task-1"


@pytest.fixture
def api(store, monkeypatch):
    """A PROFILE=local app whose implicit identity is the user id "local"."""
    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.course as course_mod

        manager = RecordingLearningManager()
        monkeypatch.setattr(course_mod, "_get_learning_manager", lambda: manager)
        yield TestClient(app, base_url="http://localhost"), manager


def test_preferences_endpoint_reports_nothing_stored(api):
    client, _ = api

    body = client.get("/api/v1/course/chaoxing/preferences").json()

    assert body == {"status": "success", "preferences": None, "has_answer_bank": False}


def test_preferences_endpoints_round_trip_without_leaking_secrets(api):
    client, _ = api

    assert client.put("/api/v1/course/chaoxing/preferences", json=FULL_PREFS).json() == {"status": "success"}
    response = client.get("/api/v1/course/chaoxing/preferences")

    assert response.status_code == 200
    body = response.json()
    assert body["has_answer_bank"] is True
    assert body["preferences"]["tiku_token"] == SECRET_MASK
    assert body["preferences"]["ai_key"] == SECRET_MASK
    assert body["preferences"]["speed"] == 2.0
    assert "yanxi-secret-token" not in response.text
    assert "sk-super-secret-key" not in response.text


def test_saving_preferences_never_starts_a_task(api):
    client, manager = api

    client.put("/api/v1/course/chaoxing/preferences", json=FULL_PREFS)

    assert manager.payloads == []


def test_preferences_require_authentication():
    """Server profile: the routes sit behind the JWT gate, not the public list."""
    with build_app("server", ENFORCE_HTTPS="false") as app:
        client = TestClient(app, base_url="http://localhost")
        assert client.get("/api/v1/course/chaoxing/preferences").status_code == 401
        assert client.put("/api/v1/course/chaoxing/preferences", json={"speed": 1.0}).status_code == 401


def test_start_with_a_full_payload_is_unchanged_by_stored_preferences(api):
    client, manager = api
    client.put("/api/v1/course/chaoxing/preferences", json=FULL_PREFS)

    response = client.post(
        "/api/v1/course/start",
        json={
            "platform": "chaoxing",
            "username": "u",
            "password": "p",
            "course_ids": ["c1"],
            "speed": 1.0,
            "concurrency": 4,
            "unopened_strategy": "retry",
            "tiku_config": {"provider": "TikuGo", "token": ""},
            "notify_config": {},
        },
    )

    assert response.status_code == 200
    payload = manager.payloads[0]
    assert payload["speed"] == 1.0
    assert payload["concurrency"] == 4
    assert payload["unopened_strategy"] == "retry"
    assert payload["tiku_config"] == {"provider": "TikuGo", "token": ""}
    assert payload["notify_config"] == {}


def test_start_with_a_minimal_payload_picks_up_stored_preferences(api):
    client, manager = api
    client.put("/api/v1/course/chaoxing/preferences", json=FULL_PREFS)

    response = client.post(
        "/api/v1/course/start",
        json={"platform": "chaoxing", "username": "u", "password": "p", "course_ids": ["c1"]},
    )

    assert response.status_code == 200
    payload = manager.payloads[0]
    assert payload["speed"] == 2.0
    assert payload["concurrency"] == 8
    assert payload["unopened_strategy"] == "continue"
    assert payload["tiku_config"]["token"] == "yanxi-secret-token"
    assert payload["tiku_config"]["provider"] == "TikuYanxi,TikuGo"
    assert payload["notify_config"] == {"service": "bark", "url": "https://push.example.com/token"}


def test_an_explicit_value_wins_over_the_stored_one(api):
    client, manager = api
    client.put("/api/v1/course/chaoxing/preferences", json=FULL_PREFS)

    client.post(
        "/api/v1/course/start",
        json={"platform": "chaoxing", "username": "u", "password": "p", "course_ids": ["c1"], "speed": 1.0},
    )

    payload = manager.payloads[0]
    assert payload["speed"] == 1.0  # explicit wins
    assert payload["concurrency"] == 8  # omitted -> stored


def test_start_with_a_minimal_payload_and_no_preferences_keeps_the_old_defaults(api):
    client, manager = api

    client.post(
        "/api/v1/course/start",
        json={"platform": "chaoxing", "username": "u", "password": "p", "course_ids": ["c1"]},
    )

    payload = manager.payloads[0]
    assert payload["speed"] == 1.0
    assert payload["concurrency"] == 4
    assert payload["unopened_strategy"] == "retry"
    assert payload["tiku_config"] == {}
    assert payload["notify_config"] == {}
