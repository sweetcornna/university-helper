"""Regression tests for atomic database backup publication."""

import os
import subprocess
from pathlib import Path
from typing import TypedDict

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "db_backup.sh"
STAMP = "2099-01-02-0304"


class BackupFixture(TypedDict):
    backup_dir: Path
    env_path: Path
    env: dict[str, str]


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
if [[ "${1:-}" == "+%F-%H%M" ]]; then
  printf '%s\\n' "$BACKUP_STAMP"
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


@pytest.mark.parametrize("failed_stage", ["dump", "gzip", "age"])
def test_failed_pipeline_does_not_publish_or_disturb_existing_backup(
    backup_fixture, failed_stage
):
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    final = backup_dir / f"uh-{STAMP}.sql.gz.age"
    known_good = b"known-good-backup\n"
    final.write_bytes(known_good)
    final.chmod(0o600)

    result = _run_backup(backup_fixture, STUB_FAIL_STAGE=failed_stage)

    assert result.returncode != 0
    assert final.read_bytes() == known_good
    assert [path.name for path in backup_dir.iterdir()] == [final.name]
    assert not list(backup_dir.glob(f".uh-{STAMP}*"))


def test_success_publishes_only_complete_final_backup(backup_fixture):
    result = _run_backup(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]
    final = backup_dir / f"uh-{STAMP}.sql.gz.age"

    assert result.returncode == 0, result.stderr
    assert final.read_bytes() == b"age:gzip:dump-payload\n"
    assert final.stat().st_mode & 0o777 == 0o600
    assert [path.name for path in backup_dir.iterdir()] == [final.name]
    assert not list(backup_dir.glob(f".uh-{STAMP}*"))
    assert "backup ok (" in result.stdout
    assert "encryption=recipient" in result.stdout


def test_encrypted_env_snapshot_is_atomic_and_restricted(backup_fixture):
    source = backup_fixture["env_path"]
    source.write_text("DATABASE_URL=postgres://secret\n", encoding="utf-8")

    result = _run_backup(backup_fixture)
    backup_dir = backup_fixture["backup_dir"]
    db_final = backup_dir / f"uh-{STAMP}.sql.gz.age"
    env_final = backup_dir / f".env.{STAMP}.age"

    assert result.returncode == 0, result.stderr
    assert env_final.read_bytes() == b"age:DATABASE_URL=postgres://secret\n"
    assert env_final.stat().st_mode & 0o777 == 0o600
    assert {path.name for path in backup_dir.iterdir()} == {
        db_final.name,
        env_final.name,
    }
    assert not list(backup_dir.glob(f".env.{STAMP}.age.*"))
    assert "env snapshotted (encrypted)" in result.stdout


def test_env_age_failure_keeps_existing_snapshot_and_published_database(backup_fixture):
    source = backup_fixture["env_path"]
    source.write_text("DATABASE_URL=postgres://new-secret\n", encoding="utf-8")
    backup_dir = backup_fixture["backup_dir"]
    backup_dir.mkdir()
    env_final = backup_dir / f".env.{STAMP}.age"
    known_good_env = b"known-good-env-snapshot\n"
    env_final.write_bytes(known_good_env)
    env_final.chmod(0o600)

    result = _run_backup(backup_fixture, STUB_FAIL_AGE_CALL="2")
    db_final = backup_dir / f"uh-{STAMP}.sql.gz.age"

    assert result.returncode != 0
    assert db_final.read_bytes() == b"age:gzip:dump-payload\n"
    assert db_final.stat().st_mode & 0o777 == 0o600
    assert env_final.read_bytes() == known_good_env
    assert {path.name for path in backup_dir.iterdir()} == {
        env_final.name,
        db_final.name,
    }
    assert not list(backup_dir.glob(f".env.{STAMP}.age.*"))
    assert not list(backup_dir.glob(f".uh-{STAMP}*"))


def test_plaintext_mode_keeps_final_name_and_allow_unencrypted_contract(backup_fixture):
    source = backup_fixture["env_path"]
    source.write_text("PLAINTEXT_SECRET=keep\n", encoding="utf-8")

    result = _run_backup(backup_fixture, AGE_RECIPIENT="", ALLOW_UNENCRYPTED="1")
    backup_dir = backup_fixture["backup_dir"]
    db_final = backup_dir / f"uh-{STAMP}.sql.gz"
    env_final = backup_dir / f".env.{STAMP}"

    assert result.returncode == 0, result.stderr
    assert db_final.read_bytes() == b"gzip:dump-payload\n"
    assert env_final.read_bytes() == b"PLAINTEXT_SECRET=keep\n"
    assert db_final.stat().st_mode & 0o777 == 0o600
    assert env_final.stat().st_mode & 0o777 == 0o600
    assert {path.name for path in backup_dir.iterdir()} == {
        db_final.name,
        env_final.name,
    }
    assert not list(backup_dir.glob(f".env.{STAMP}.*"))
    assert "encryption=disabled" in result.stdout
