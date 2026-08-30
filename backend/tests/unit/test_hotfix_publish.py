"""Regression tests for the hotfix publisher's repository-path boundary."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_SOURCE = Path(__file__).resolve().parents[3] / "scripts" / "hotfix_publish.sh"


@pytest.fixture
def publisher_fixture(tmp_path):
    workspace = tmp_path / "workspace"
    repo = workspace / "repo"
    script = repo / "scripts" / "hotfix_publish.sh"
    target = repo / "backend" / "app" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_text("print('fixture')\n")
    script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT_SOURCE, script)

    outside = tmp_path / "secret.txt"
    outside.write_text("do not publish\n")
    escape = target.parent / "escape.py"
    escape.symlink_to(outside)
    for unsafe_name in ("quote'name.py", "bad\nname.py", "$(touch_marker).py"):
        (target.parent / unsafe_name).write_text("must not publish\n")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    call_log = tmp_path / "network-calls.log"
    call_marker = tmp_path / "network-called"
    fake_transport = """#!/usr/bin/env bash
printf '%s\\n' "$0" >> "$CALL_LOG"
printf '%s\\n' "$@" >> "$CALL_LOG"
: > "$CALL_MARKER"
exit 0
"""
    for command in ("ssh", "scp"):
        transport = fake_bin / command
        transport.write_text(fake_transport)
        transport.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "CALL_LOG": str(call_log),
            "CALL_MARKER": str(call_marker),
            "SERVER_IP": "test.invalid",
            "SERVER_USER": "tester",
            "EASY_LEARNING_REMOTE_DIR": "/opt/university-helper",
        }
    )
    return {
        "repo": repo,
        "script": script,
        "outside": outside,
        "env": env,
        "call_log": call_log,
        "call_marker": call_marker,
    }


def run_publisher(fixture, *paths):
    return subprocess.run(
        [str(fixture["script"]), *paths],
        cwd=fixture["repo"],
        env=fixture["env"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_normal_relative_file_keeps_remote_target_semantics(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py")

    assert result.returncode == 0, result.stderr
    log = publisher_fixture["call_log"].read_text()
    assert "mkdir -p '/opt/university-helper/backend/app'" in log
    assert "tester@test.invalid:/opt/university-helper/backend/app/main.py" in log
    assert "docker cp '/opt/university-helper/backend/app/main.py' 'shuake-easy-learning-app:/srv/backend/app/main.py'" in log
    assert publisher_fixture["call_marker"].exists()


@pytest.mark.parametrize(
    "malicious_path",
    [
        "../../secret.txt",
        "backend/app/escape.py",
        "backend/app/quote'name.py",
        "backend/app/bad\nname.py",
        "backend/app/$(touch_marker).py",
    ],
)
def test_malicious_path_is_rejected_before_network_calls(publisher_fixture, malicious_path):
    result = run_publisher(publisher_fixture, malicious_path)

    assert result.returncode != 0
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()


def test_late_invalid_path_does_not_publish_an_earlier_valid_path(publisher_fixture):
    result = run_publisher(publisher_fixture, "backend/app/main.py", "../../secret.txt")

    assert result.returncode != 0
    assert not publisher_fixture["call_marker"].exists()
    assert not publisher_fixture["call_log"].exists()
