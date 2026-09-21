"""Fault-injection tests for the one-shot server cutover helper."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "server_finalize_shuake_cutover.sh"
STAMP = "20260830-120000"
DOMAIN = "example.test"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fixture(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    backup_dir = tmp_path / "backups"
    nginx_dir = tmp_path / "nginx"
    private_tmp = tmp_path / "private-tmp"
    for directory in (bin_dir, backup_dir, nginx_dir, private_tmp):
        directory.mkdir()

    _write_executable(
        bin_dir / "date",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "+%Y%m%d-%H%M%S" ]]; then
  printf '%s\n' '20260830-120000'
else
  printf '%s\n' '2026-08-30T12:00:00+00:00'
fi
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
args="$*"
printf '%s\n' "$args" >> "$FAKE_LOG"

if [[ "$args" == *"pg_dump"* ]]; then
  if [[ "$args" != *"-t users"* ]]; then
    printf '%s\n' 'legacy-dump'
    [[ "${DUMP_FAIL:-0}" != "1" ]] || exit 21
  elif [[ "$args" == *"--schema-only"* ]]; then
    printf '%s\n' 'users-schema'
  else
    printf '%s\n' 'users-data'
  fi
  exit 0
fi

if [[ "$args" == *"psql"* ]]; then
  [[ "${PSQL_FAIL:-0}" != "1" ]] || exit 26
  if [[ "$args" == *"information_schema"* ]]; then
    printf '%s\n' "${USERS_EXISTS:-0}"
  elif [[ "$args" == *"select count(*) from users;"* ]]; then
    printf '%s\n' "${USERS_COUNT:-0}"
  else
    cat >/dev/null
  fi
  exit 0
fi

exit 0
""",
    )
    _write_executable(
        bin_dir / "gzip",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -c)
    cat
    [[ "${GZIP_STREAM_FAIL:-0}" != "1" ]] || exit 23
    ;;
  -t)
    [[ "${GZIP_TEST_FAIL:-0}" != "1" ]] || exit 24
    [[ -s "${2:?missing gzip test path}" ]]
    ;;
  *)
    exit 2
    ;;
esac
""",
    )
    _write_executable(
        bin_dir / "nginx",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_LOG"
[[ "${1:-}" == "-t" && "${2:-}" == "-c" ]] || exit 2
validation_conf="$3"
[[ -f "$validation_conf" ]] || exit 3
candidate="$(awk -F'\"' '/include / { print $2; exit }' "$validation_conf")"
[[ -n "$candidate" && -f "$candidate" ]] || exit 4
printf '%s' "$candidate" > "$NGINX_VALIDATED_CANDIDATE"
grep -q "server_name ${DOMAIN};" "$candidate"
[[ "${NGINX_TEST_FAIL:-0}" != "1" ]] || exit 29
""",
    )
    _write_executable(
        bin_dir / "systemctl",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_LOG"
[[ "$*" == "reload nginx" ]] || exit 2
[[ "${RELOAD_FAIL:-0}" != "1" ]] || exit 31
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', os.defpath)}",
            "TMPDIR": str(private_tmp),
            "BACKUP_DIR": str(backup_dir),
            "NGINX_CONFIG_DIR": str(nginx_dir),
            "DOMAIN": DOMAIN,
            "PROJECT_DIR": str(tmp_path / "project"),
            "FAKE_LOG": str(tmp_path / "fake.log"),
            "NGINX_VALIDATED_CANDIDATE": str(tmp_path / "validated-candidate"),
            "USERS_EXISTS": "0",
            "USERS_COUNT": "0",
        }
    )
    return env, backup_dir, nginx_dir, private_tmp


def _backup_path(backup_dir: Path) -> Path:
    return backup_dir / f"shuake-main_db-{STAMP}.sql.gz"


def _nginx_target(nginx_dir: Path) -> Path:
    return nginx_dir / DOMAIN


def _assert_no_temporary_files(
    backup_dir: Path, nginx_dir: Path, private_tmp: Path
) -> None:
    assert not list(backup_dir.glob(".shuake-main_db-*"))
    assert not list(nginx_dir.glob(".server.*"))
    assert not list(private_tmp.iterdir())


def _prepare_existing_backup(backup_dir: Path) -> Path:
    path = _backup_path(backup_dir)
    path.write_text("old-backup", encoding="utf-8")
    path.chmod(0o640)
    return path


@pytest.mark.parametrize("failure", [{"DUMP_FAIL": "1"}, {"GZIP_STREAM_FAIL": "1"}])
def test_backup_pipeline_failure_preserves_existing_file_and_cleans_temp(
    tmp_path: Path, failure: dict[str, str]
) -> None:
    env, backup_dir, nginx_dir, private_tmp = _fixture(tmp_path)
    existing = _prepare_existing_backup(backup_dir)
    env.update(failure)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == "old-backup"
    assert stat.S_IMODE(existing.stat().st_mode) == 0o640
    _assert_no_temporary_files(backup_dir, nginx_dir, private_tmp)


def test_gzip_validation_failure_preserves_existing_file_and_cleans_temp(
    tmp_path: Path,
) -> None:
    env, backup_dir, nginx_dir, private_tmp = _fixture(tmp_path)
    existing = _prepare_existing_backup(backup_dir)
    env["GZIP_TEST_FAIL"] = "1"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert existing.read_text(encoding="utf-8") == "old-backup"
    _assert_no_temporary_files(backup_dir, nginx_dir, private_tmp)


def test_psql_failure_keeps_completed_backup_and_private_sql_is_cleaned(
    tmp_path: Path,
) -> None:
    env, backup_dir, nginx_dir, private_tmp = _fixture(tmp_path)
    env["PSQL_FAIL"] = "1"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    completed_backup = _backup_path(backup_dir)
    assert completed_backup.read_text(encoding="utf-8") == "legacy-dump\n"
    assert stat.S_IMODE(completed_backup.stat().st_mode) == 0o600
    _assert_no_temporary_files(backup_dir, nginx_dir, private_tmp)


def test_success_publishes_only_complete_backup_and_nginx_config(
    tmp_path: Path,
) -> None:
    env, backup_dir, nginx_dir, private_tmp = _fixture(tmp_path)
    nginx_target = _nginx_target(nginx_dir)
    nginx_target.write_text("old nginx config\n", encoding="utf-8")
    nginx_target.chmod(0o600)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "[1/6] Backing up legacy database to" in result.stdout
    assert "[5/6] Repointing host Nginx" in result.stdout
    assert "Cutover complete." in result.stdout
    backup = _backup_path(backup_dir)
    assert backup.read_text(encoding="utf-8") == "legacy-dump\n"
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    config = nginx_target.read_text(encoding="utf-8")
    assert "server_name example.test;" in config
    assert "proxy_pass http://127.0.0.1:18082;" in config
    assert stat.S_IMODE(nginx_target.stat().st_mode) == 0o600
    nginx_backup = nginx_dir / f"{DOMAIN}.bak-{STAMP}"
    assert f"Backup: {backup}" in result.stdout
    assert f"Nginx backup: {nginx_backup}" in result.stdout
    assert nginx_backup.read_text(encoding="utf-8") == "old nginx config\n"

    validated_candidate = Path(
        Path(env["NGINX_VALIDATED_CANDIDATE"]).read_text(encoding="utf-8")
    )
    assert validated_candidate.parent == nginx_dir
    assert validated_candidate != nginx_target
    assert not validated_candidate.exists()
    assert "-t -c" in (tmp_path / "fake.log").read_text(encoding="utf-8")
    _assert_no_temporary_files(backup_dir, nginx_dir, private_tmp)


def test_nginx_validation_failure_preserves_old_config_and_cleans_temp(
    tmp_path: Path,
) -> None:
    env, backup_dir, nginx_dir, private_tmp = _fixture(tmp_path)
    nginx_target = _nginx_target(nginx_dir)
    nginx_target.write_text("old nginx config\n", encoding="utf-8")
    nginx_target.chmod(0o600)
    env["NGINX_TEST_FAIL"] = "1"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert nginx_target.read_text(encoding="utf-8") == "old nginx config\n"
    assert (nginx_dir / f"{DOMAIN}.bak-{STAMP}").read_text(
        encoding="utf-8"
    ) == "old nginx config\n"
    assert _backup_path(backup_dir).exists()
    validated_candidate = Path(
        Path(env["NGINX_VALIDATED_CANDIDATE"]).read_text(encoding="utf-8")
    )
    assert not validated_candidate.exists()
    _assert_no_temporary_files(backup_dir, nginx_dir, private_tmp)


def test_nginx_reload_failure_rolls_back_atomic_install(tmp_path: Path) -> None:
    env, backup_dir, nginx_dir, private_tmp = _fixture(tmp_path)
    nginx_target = _nginx_target(nginx_dir)
    nginx_target.write_text("old nginx config\n", encoding="utf-8")
    nginx_target.chmod(0o600)
    env["RELOAD_FAIL"] = "1"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert nginx_target.read_text(encoding="utf-8") == "old nginx config\n"
    assert not (nginx_dir / f"{DOMAIN}.bak-{STAMP}").exists()
    assert _backup_path(backup_dir).exists()
    _assert_no_temporary_files(backup_dir, nginx_dir, private_tmp)
