"""Regression tests for frontend hotfix publication transport arguments."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hotfix_publish.sh"
SERVER_IP = "example.test"
SERVER_USER = "deployer"
REMOTE_DIR = "/srv/university-helper"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def frontend_fixture(tmp_path: Path) -> tuple[dict[str, str], dict[str, Path]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        f"{SERVER_IP} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey\n",
        encoding="utf-8",
    )
    transport_logs = {
        "ssh": tmp_path / "ssh-calls",
        "scp": tmp_path / "scp-calls",
        "rsync": tmp_path / "rsync-argv",
    }

    # The script validates the known_hosts syntax and matching host through
    # ssh-keygen.  This stub keeps the test focused on the rsync invocation.
    _write_executable(
        fake_bin / "ssh-keygen",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -lf)
    cat >/dev/null
    ;;
  -F)
    printf '%s ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey\\n' "$2"
    ;;
  *)
    exit 2
    ;;
esac
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"$SSH_CALLS_LOG"
exit 0
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"$SCP_CALLS_LOG"
exit 0
""",
    )
    _write_executable(
        fake_bin / "rsync",
        """#!/usr/bin/env bash
set -euo pipefail
: >"$RSYNC_ARGV_LOG"
for argument in "$@"; do
  printf '%s\\n' "$argument" >>"$RSYNC_ARGV_LOG"
done
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', os.defpath)}",
            "SERVER_IP": SERVER_IP,
            "SERVER_USER": SERVER_USER,
            "EASY_LEARNING_REMOTE_DIR": REMOTE_DIR,
            "SSH_KNOWN_HOSTS_FILE": str(known_hosts),
            "SSH_CALLS_LOG": str(transport_logs["ssh"]),
            "SCP_CALLS_LOG": str(transport_logs["scp"]),
            "RSYNC_ARGV_LOG": str(transport_logs["rsync"]),
        }
    )
    return env, transport_logs


def test_frontend_rsync_target_has_no_literal_shell_quotes(
    frontend_fixture: tuple[dict[str, str], dict[str, Path]],
) -> None:
    env, transport_logs = frontend_fixture
    result = subprocess.run(
        ["bash", str(SCRIPT), "--frontend"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    argv = transport_logs["rsync"].read_text(encoding="utf-8").splitlines()
    assert argv[:2] == ["-az", "--delete"]
    assert argv[2] == "-e"
    assert argv[4] == f"{REPO_ROOT}/frontend/dist/"
    assert argv[5] == f"{SERVER_USER}@{SERVER_IP}:{REMOTE_DIR}/frontend/dist/"
    assert "'" not in argv[5]


def test_frontend_rejects_unsafe_remote_dir_before_transport(
    frontend_fixture: tuple[dict[str, str], dict[str, Path]],
) -> None:
    env, transport_logs = frontend_fixture
    env["EASY_LEARNING_REMOTE_DIR"] = "/opt/university-helper;touch"

    result = subprocess.run(
        ["bash", str(SCRIPT), "--frontend"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid EASY_LEARNING_REMOTE_DIR" in result.stdout
    for log_path in transport_logs.values():
        assert not log_path.exists() or log_path.read_text(encoding="utf-8") == ""
