"""Regression tests for atomic database backup publication."""

import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "db_backup.sh"
STAMP = "2099-01-02-030405"


class BackupFixture(TypedDict):
    backup_dir: Path
    env_path: Path
    env: dict[str, str]
    fake_bin: Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def backup_fixture(tmp_path: Path) -> BackupFixture:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    env_path = tmp_path / "source.env"

    _write_executable(
        fake_bin / "date",
        """#!/usr/bin/env bash
if [[ "${1:-}" == "+%F-%H%M%S" ]]; then
  printf '%s\\n' "$BACKUP_STAMP"
elif [[ "${1:-}" == "+%s" ]]; then
  printf '%s\\n' "$BACKUP_EPOCH"
else
  printf '%s\\n' '2099-01-02T03:04:05+00:00'
fi
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
if [[ "${STUB_FAIL_STAGE:-}" == "dump" ]]; then
  printf '%s\\n' 'dump-partial'
  exit 41
fi
printf '%s\\n' 'dump-payload'
""",
    )
    _write_executable(
        fake_bin / "gzip",
        """#!/usr/bin/env bash
payload=$(cat)
if [[ "${STUB_FAIL_STAGE:-}" == "gzip" ]]; then
  printf '%s\\n' 'gzip-partial'
  exit 42
fi
printf 'gzip:%s\\n' "$payload"
""",
    )
    _write_executable(
        fake_bin / "age",
        """#!/usr/bin/env bash
call_number=0
if [[ -n "${AGE_CALL_COUNT_FILE:-}" && -f "$AGE_CALL_COUNT_FILE" ]]; then
  call_number=$(<"$AGE_CALL_COUNT_FILE")
fi
call_number=$((call_number + 1))
if [[ -n "${AGE_CALL_COUNT_FILE:-}" ]]; then
  printf '%s\\n' "$call_number" > "$AGE_CALL_COUNT_FILE"
fi
payload=$(cat)
if [[ "${STUB_FAIL_STAGE:-}" == "age" || "${STUB_FAIL_AGE_CALL:-}" == "$call_number" ]]; then
  printf '%s\\n' 'age-partial'
  exit 43
fi
printf 'age:%s\\n' "$payload"
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "BACKUP_STAMP": STAMP,
            "BACKUP_EPOCH": str(int(time.time())),
            "BACKUP_CONTAINER": "test-db",
            "POSTGRES_USER": "test-user",
            "AGE_RECIPIENT": "age1testrecipient",
            "ENV_PATH": str(env_path),
            "AGE_CALL_COUNT_FILE": str(tmp_path / "age-calls"),
            "RETAIN_DAYS": "14",
        }
    )
    return {
        "backup_dir": tmp_path / "backups",
        "env_path": env_path,
        "env": env,
        "fake_bin": fake_bin,
    }


def _run_backup(
    fixture: BackupFixture, **env_overrides: str
) -> subprocess.CompletedProcess[str]:
    env = fixture["env"].copy()
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT), str(fixture["backup_dir"])],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _db_backups(backup_dir: Path, encrypted: bool = True) -> list[Path]:
    suffix = ".sql.gz.age" if encrypted else ".sql.gz"
    return sorted(backup_dir.glob(f"uh-*{suffix}"))


def _env_backups(backup_dir: Path, encrypted: bool = True) -> list[Path]:
    suffix = ".age" if encrypted else ""
    return sorted(backup_dir.glob(f".env.*{suffix}"))


def _group_id(path: Path) -> str:
    if path.name.startswith("uh-"):
        return (
            path.name.removeprefix("uh-")
            .removesuffix(".sql.gz.age")
            .removesuffix(".sql.gz")
        )
    return path.name.removeprefix(".env.").removesuffix(".age")


def _install_mktemp_stub(fixture: BackupFixture, group_suffix: str = "ABC123") -> None:
    _write_executable(
        fixture["fake_bin"] / "mktemp",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "-d" ]]; then
  template="$2"
  target="${{template//XXXXXX/{group_suffix}}}"
  mkdir "$target"
else
  template="$1"
  target="${{template//XXXXXX/{group_suffix}}}"
  : > "$target"
fi
printf '%s\\n' "$target"
""",
    )


@pytest.mark.parametrize("failed_stage", ["dump", "gzip", "age"])
def test_failed_pipeline_does_not_publish_or_disturb_existing_backup(
    backup_fixture, failed_stage
):
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    final = backup_dir / f"uh-{STAMP}.existing.sql.gz.age"
    known_good = b"known-good-backup\n"
    final.write_bytes(known_good)
    final.chmod(0o600)

    result = _run_backup(backup_fixture, STUB_FAIL_STAGE=failed_stage)

    assert result.returncode != 0
    assert final.read_bytes() == known_good
    assert [path.name for path in backup_dir.iterdir()] == [final.name]
    assert not list(backup_dir.glob(".uh-*"))


def test_success_publishes_only_complete_final_backup(backup_fixture):
    result = _run_backup(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]
    db_backups = _db_backups(backup_dir)

    assert result.returncode == 0, result.stderr
    assert len(db_backups) == 1
    final = db_backups[0]
    assert final.name.startswith(f"uh-{STAMP}.")
    assert final.read_bytes() == b"age:gzip:dump-payload\n"
    assert final.stat().st_mode & 0o777 == 0o600
    assert [path.name for path in backup_dir.iterdir()] == [final.name]
    assert not list(backup_dir.glob(".uh-*"))
    assert "backup ok (" in result.stdout
    assert "encryption=recipient" in result.stdout


def test_encrypted_env_snapshot_is_atomic_and_restricted(backup_fixture):
    source = backup_fixture["env_path"]
    source.write_text("DATABASE_URL=postgres://secret\n", encoding="utf-8")

    result = _run_backup(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]
    db_backups = _db_backups(backup_dir)
    env_backups = _env_backups(backup_dir)

    assert result.returncode == 0, result.stderr
    assert len(db_backups) == 1
    assert len(env_backups) == 1
    db_final = db_backups[0]
    env_final = env_backups[0]
    assert _group_id(db_final) == _group_id(env_final)
    assert env_final.read_bytes() == b"age:DATABASE_URL=postgres://secret\n"
    assert env_final.stat().st_mode & 0o777 == 0o600
    assert {path.name for path in backup_dir.iterdir()} == {
        db_final.name,
        env_final.name,
    }
    assert not list(backup_dir.glob(".env.*.age.*"))
    assert not list(backup_dir.glob(".uh-*"))
    assert "env snapshotted (encrypted)" in result.stdout


def test_env_age_failure_keeps_existing_snapshot_and_published_database(backup_fixture):
    source = backup_fixture["env_path"]
    source.write_text("DATABASE_URL=postgres://new-secret\n", encoding="utf-8")
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    env_final = backup_dir / f".env.{STAMP}.existing.age"
    known_good_env = b"known-good-env-snapshot\n"
    env_final.write_bytes(known_good_env)
    env_final.chmod(0o600)

    result = _run_backup(backup_fixture, STUB_FAIL_AGE_CALL="2")
    db_backups = _db_backups(backup_dir)

    assert result.returncode != 0
    assert len(db_backups) == 1
    db_final = db_backups[0]
    assert db_final.read_bytes() == b"age:gzip:dump-payload\n"
    assert db_final.stat().st_mode & 0o777 == 0o600
    assert env_final.read_bytes() == known_good_env
    assert {path.name for path in backup_dir.iterdir()} == {
        env_final.name,
        db_final.name,
    }
    assert not list(backup_dir.glob(".env.*.age.*"))
    assert not list(backup_dir.glob(".uh-*"))


def test_plaintext_mode_keeps_final_name_and_allow_unencrypted_contract(backup_fixture):
    source = backup_fixture["env_path"]
    source.write_text("PLAINTEXT_SECRET=keep\n", encoding="utf-8")

    result = _run_backup(backup_fixture, AGE_RECIPIENT="", ALLOW_UNENCRYPTED="1")
    backup_dir = backup_fixture["backup_dir"]
    db_backups = _db_backups(backup_dir, encrypted=False)
    env_backups = _env_backups(backup_dir, encrypted=False)

    assert result.returncode == 0, result.stderr
    assert len(db_backups) == 1
    assert len(env_backups) == 1
    db_final = db_backups[0]
    env_final = env_backups[0]
    assert _group_id(db_final) == _group_id(env_final)
    assert db_final.read_bytes() == b"gzip:dump-payload\n"
    assert env_final.read_bytes() == b"PLAINTEXT_SECRET=keep\n"
    assert db_final.stat().st_mode & 0o777 == 0o600
    assert env_final.stat().st_mode & 0o777 == 0o600
    assert {path.name for path in backup_dir.iterdir()} == {
        db_final.name,
        env_final.name,
    }
    assert not list(backup_dir.glob(".env.*."))
    assert "encryption=disabled" in result.stdout


def test_fixed_timestamp_runs_publish_distinct_groups_without_overwrite(backup_fixture):
    backup_fixture["env_path"].write_text(
        "DATABASE_URL=postgres://secret\n", encoding="utf-8"
    )
    first = _run_backup(backup_fixture)
    second = _run_backup(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    db_backups = _db_backups(backup_dir)
    env_backups = _env_backups(backup_dir)
    assert len(db_backups) == 2
    assert len(env_backups) == 2
    db_groups = {_group_id(path) for path in db_backups}
    env_groups = {_group_id(path) for path in env_backups}
    assert len(db_groups) == 2
    assert db_groups == env_groups
    assert all(path.read_bytes() == b"age:gzip:dump-payload\n" for path in db_backups)
    assert not list(backup_dir.glob(".uh-*"))


def test_retention_recognizes_unique_group_names(backup_fixture):
    backup_fixture["env_path"].write_text(
        "DATABASE_URL=postgres://secret\n", encoding="utf-8"
    )
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    old_files = [
        backup_dir / "uh-2099-01-02-0304.sql.gz.age",
        backup_dir / ".env.2099-01-02-0304.age",
        backup_dir / "uh-2099-01-02-0305.sql.gz",
        backup_dir / ".env.2099-01-02-0305",
        backup_dir / "uh-2099-01-02-0306.sql.gz",
    ]
    for path in old_files:
        path.write_bytes(b"old-backup\n")
        old_time = path.stat().st_mtime - (3 * 24 * 60 * 60)
        os.utime(path, (old_time, old_time))
    mixed_group = f"{STAMP}.ABC123"
    mixed_db = backup_dir / f"uh-{mixed_group}.sql.gz"
    mixed_env = backup_dir / f".env.{mixed_group}.age"
    mixed_db.write_bytes(b"old-db-with-fresh-env\n")
    mixed_db_old_time = mixed_db.stat().st_mtime - (3 * 24 * 60 * 60)
    os.utime(mixed_db, (mixed_db_old_time, mixed_db_old_time))
    mixed_env.write_bytes(b"fresh-env\n")
    fresh_time = time.time() + 60
    os.utime(mixed_env, (fresh_time, fresh_time))
    ordinary_env = backup_dir / ".env"
    ordinary_env.write_bytes(b"ordinary-env\n")
    malformed_env = backup_dir / f".env.{STAMP}.not-a-valid-id"
    malformed_env.write_bytes(b"malformed-env\n")
    for path in (ordinary_env, malformed_env):
        old_time = path.stat().st_mtime - (3 * 24 * 60 * 60)
        os.utime(path, (old_time, old_time))

    result = _run_backup(backup_fixture, RETAIN_DAYS="0")

    assert result.returncode == 0, result.stderr
    assert all(not path.exists() for path in old_files)
    assert mixed_db.exists()
    assert mixed_env.exists()
    assert ordinary_env.read_bytes() == b"ordinary-env\n"
    assert malformed_env.read_bytes() == b"malformed-env\n"
    current_db = _db_backups(backup_dir)
    current_env = [
        path for path in _env_backups(backup_dir) if _group_id(path) != mixed_group
    ]
    assert len(current_db) == 1
    assert len(current_env) == 1
    assert _group_id(current_db[0]) == _group_id(current_env[0])


@pytest.mark.parametrize(
    ("raw_days", "parsed_days"), [("08", 8), ("09", 9), ("010", 10)]
)
def test_retention_days_are_parsed_as_decimal(
    backup_fixture, raw_days, parsed_days
):
    result = _run_backup(backup_fixture, RETAIN_DAYS=raw_days)

    assert result.returncode == 0, result.stderr
    assert f"retention pruned (>{parsed_days} days)" in result.stdout
    assert len(_db_backups(backup_fixture["backup_dir"])) == 1
    assert not list(backup_fixture["backup_dir"].glob(".uh-*"))


@pytest.mark.parametrize(
    "invalid_days", ["", "-1", "36501", "999999999999999999999999", "1day"]
)
def test_invalid_retention_days_fail_before_side_effects(
    backup_fixture, invalid_days
):
    result = _run_backup(backup_fixture, RETAIN_DAYS=invalid_days)

    assert result.returncode == 2
    assert not backup_fixture["backup_dir"].exists()
    assert not Path(backup_fixture["env"]["AGE_CALL_COUNT_FILE"]).exists()


@pytest.mark.parametrize("target_kind", ["file", "directory", "symlink"])
def test_existing_final_target_fails_without_losing_source(backup_fixture, target_kind):
    _install_mktemp_stub(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    target = backup_dir / f"uh-{STAMP}.ABC123.sql.gz.age"
    if target_kind == "file":
        target.write_bytes(b"known-good\n")
        target.chmod(0o600)
    elif target_kind == "directory":
        target.mkdir()
        sentinel = target / "sentinel"
        sentinel.write_bytes(b"directory-preserved\n")
    else:
        sentinel = backup_dir / "target-sentinel"
        sentinel.write_bytes(b"target-preserved\n")
        target.symlink_to(sentinel)

    result = _run_backup(backup_fixture)

    assert result.returncode != 0
    if target_kind == "file":
        assert target.read_bytes() == b"known-good\n"
    elif target_kind == "directory":
        assert (target / "sentinel").read_bytes() == b"directory-preserved\n"
        assert not (target / "db.ABC123").exists()
    else:
        assert target.is_symlink()
        assert target.resolve() == sentinel
        assert sentinel.read_bytes() == b"target-preserved\n"
    assert not list(backup_dir.glob("*.reserve"))
    assert not list(backup_dir.glob(".uh-*"))


@pytest.mark.parametrize(
    ("signal_name", "signal_number"),
    [("HUP", signal.SIGHUP), ("INT", signal.SIGINT), ("TERM", signal.SIGTERM)],
)
def test_signal_after_reservation_mkdir_removes_only_unpublished_work(
    backup_fixture, signal_name, signal_number
):
    _install_mktemp_stub(backup_fixture)

    result = _run_backup(
        backup_fixture,
        DB_BACKUP_TEST_MODE="1",
        DB_BACKUP_TEST_SIGNAL_AFTER_RESERVATION_MKDIR=signal_name,
    )
    backup_dir = backup_fixture["backup_dir"]

    assert result.returncode == 128 + signal_number
    assert not _db_backups(backup_dir)
    assert not list(backup_dir.glob("*.reserve"))
    assert not list(backup_dir.glob(".uh-*"))


def test_failed_reservation_mkdir_preserves_other_owner(backup_fixture):
    _install_mktemp_stub(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    destination = backup_dir / f"uh-{STAMP}.ABC123.sql.gz.age"
    reservation = Path(f"{destination}.reserve")
    reservation.mkdir()
    other_owner = reservation / "other-owner"
    other_owner.write_text("keep\n", encoding="utf-8")

    result = _run_backup(backup_fixture)

    assert result.returncode != 0
    assert reservation.is_dir()
    assert other_owner.read_text(encoding="utf-8") == "keep\n"
    assert not destination.exists()
    assert not list(backup_dir.glob(".uh-*"))


def test_signal_after_atomic_link_keeps_published_target(backup_fixture):
    _install_mktemp_stub(backup_fixture)

    result = _run_backup(
        backup_fixture,
        DB_BACKUP_TEST_MODE="1",
        DB_BACKUP_TEST_SIGNAL_AFTER_PUBLISH_LINK="TERM",
    )
    backup_dir = backup_fixture["backup_dir"]
    destination = backup_dir / f"uh-{STAMP}.ABC123.sql.gz.age"

    assert result.returncode == 128 + signal.SIGTERM
    assert destination.read_bytes() == b"age:gzip:dump-payload\n"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert not list(backup_dir.glob("*.reserve"))
    assert not list(backup_dir.glob(".uh-*"))


@pytest.mark.parametrize(
    "hook_name",
    [
        "DB_BACKUP_TEST_SIGNAL_AFTER_RESERVATION_MKDIR",
        "DB_BACKUP_TEST_SIGNAL_AFTER_PUBLISH_LINK",
    ],
)
@pytest.mark.parametrize("invalid_signal", ["KILL", "STOP", "USR1", "NOT_A_SIGNAL"])
def test_invalid_test_hook_signal_fails_before_side_effects(
    backup_fixture, hook_name, invalid_signal
):
    result = _run_backup(
        backup_fixture,
        DB_BACKUP_TEST_MODE="1",
        **{hook_name: invalid_signal},
    )

    assert result.returncode == 2
    assert not backup_fixture["backup_dir"].exists()
    assert not Path(backup_fixture["env"]["AGE_CALL_COUNT_FILE"]).exists()


@pytest.mark.parametrize("ignored_signal", ["KILL", "STOP", "NOT_A_SIGNAL"])
def test_test_hooks_are_inert_without_explicit_test_mode(
    backup_fixture, ignored_signal
):
    result = _run_backup(
        backup_fixture,
        DB_BACKUP_TEST_SIGNAL_AFTER_RESERVATION_MKDIR=ignored_signal,
        DB_BACKUP_TEST_SIGNAL_AFTER_PUBLISH_LINK=ignored_signal,
    )
    backup_dir = backup_fixture["backup_dir"]

    assert result.returncode == 0, result.stderr
    assert len(_db_backups(backup_dir)) == 1
    assert not list(backup_dir.glob("*.reserve"))
    assert not list(backup_dir.glob(".uh-*"))


def test_concurrent_fixed_timestamp_runs_do_not_collide(backup_fixture):
    backup_fixture["env_path"].write_text("PLAINTEXT_SECRET=keep\n", encoding="utf-8")
    backup_dir = backup_fixture["backup_dir"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _run_backup,
                backup_fixture,
                AGE_RECIPIENT="",
                ALLOW_UNENCRYPTED="1",
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=35) for future in futures]

    assert all(result.returncode == 0 for result in results), [
        (result.stdout, result.stderr) for result in results
    ]
    db_backups = _db_backups(backup_dir, encrypted=False)
    env_backups = _env_backups(backup_dir, encrypted=False)
    assert len(db_backups) == 2
    assert len(env_backups) == 2
    db_groups = {_group_id(path) for path in db_backups}
    env_groups = {_group_id(path) for path in env_backups}
    assert len(db_groups) == 2
    assert db_groups == env_groups
    assert all(path.read_bytes() == b"gzip:dump-payload\n" for path in db_backups)
    assert all(path.read_bytes() == b"PLAINTEXT_SECRET=keep\n" for path in env_backups)
    assert not list(backup_dir.glob(".uh-*"))
