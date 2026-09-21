"""Regression tests for the legacy automated deploy command boundary."""

from __future__ import annotations

import importlib.util
import subprocess
import types
from pathlib import Path

import pytest

SCRIPT_SOURCE = Path(__file__).resolve().parents[3] / "scripts" / "_legacy" / "deploy_auto.py"


def load_deploy_module(monkeypatch: pytest.MonkeyPatch, *, server_ip: str, server_user: str) -> types.ModuleType:
    monkeypatch.setenv("EASY_LEARNING_SERVER_IP", server_ip)
    monkeypatch.setenv("EASY_LEARNING_SERVER_USER", server_user)
    monkeypatch.setenv("EASY_LEARNING_SERVER_PASSWORD", "test-password")
    monkeypatch.setenv("EASY_LEARNING_REMOTE_DIR", "/srv/university-helper")

    spec = importlib.util.spec_from_file_location("legacy_deploy_auto_test_module", SCRIPT_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("server_user", "server_ip"),
    [
        ("deploy;touch /tmp/pwned", "deploy.example.test"),
        ("deploy$(touch /tmp/pwned)", "deploy.example.test"),
        ("deploy\ndeploy", "deploy.example.test"),
        ("deploy user", "deploy.example.test"),
        (" deploy", "deploy.example.test"),
        ("deploy", " deploy.example.test"),
        ("deploy", "10.0.0.1;touch /tmp/pwned"),
        ("deploy", "10.0.0.1$(touch /tmp/pwned)"),
        ("deploy", "10.0.0.1\n10.0.0.2"),
        ("deploy", "10.0.0.1  "),
    ],
)
def test_untrusted_server_settings_are_rejected_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    server_user: str,
    server_ip: str,
) -> None:
    module = load_deploy_module(monkeypatch, server_ip=server_ip, server_user=server_user)
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(command: object, **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        module.main()

    assert calls == []


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("EASY_LEARNING_REMOTE_DIR", "/srv/university-helper;touch /tmp/pwned"),
        ("EASY_LEARNING_REMOTE_DIR", "/srv/university-helper$(touch /tmp/pwned)"),
        ("EASY_LEARNING_REMOTE_DIR", "/srv/university-helper\nnext"),
        ("EASY_LEARNING_COMPOSE_FILE", "docker-compose.yml;touch /tmp/pwned"),
        ("EASY_LEARNING_COMPOSE_FILE", "docker-compose.yml $(touch /tmp/pwned)"),
        ("EASY_LEARNING_COMPOSE_FILE", "docker-compose.yml\nnext"),
    ],
)
def test_untrusted_remote_paths_are_rejected_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: str,
) -> None:
    module = load_deploy_module(monkeypatch, server_ip="deploy.example.test", server_user="deploy")
    monkeypatch.setenv(setting, value)
    setattr(module, setting.removeprefix("EASY_LEARNING_"), value)
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(command: object, **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        module.main()

    assert calls == []


@pytest.mark.parametrize(
    ("server_ip", "server_user", "expected_remote", "expected_file_remote"),
    [
        (
            "192.0.2.20",
            "deploy-user",
            "deploy-user@192.0.2.20",
            "deploy-user@192.0.2.20:/srv/university-helper/.env",
        ),
        (
            "deploy.example.test",
            "deploy_user",
            "deploy_user@deploy.example.test",
            "deploy_user@deploy.example.test:/srv/university-helper/.env",
        ),
        (
            "2001:db8::20",
            "deploy",
            "deploy@2001:db8::20",
            "deploy@[2001:db8::20]:/srv/university-helper/.env",
        ),
    ],
)
def test_valid_server_settings_build_argv_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
    server_ip: str,
    server_user: str,
    expected_remote: str,
    expected_file_remote: str,
) -> None:
    module = load_deploy_module(monkeypatch, server_ip=server_ip, server_user=server_user)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.main()

    assert len(calls) == 4
    for command, kwargs in calls:
        assert isinstance(command, list)
        assert kwargs == {"shell": False, "check": True}
        assert "StrictHostKeyChecking=no" not in command

    assert calls[0][0][:6] == [
        "sshpass",
        "-p",
        "test-password",
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    assert calls[0][0][6:] == [expected_remote, "mkdir -p /srv/university-helper"]

    rsync_command = calls[1][0]
    assert rsync_command[:5] == ["sshpass", "-p", "test-password", "rsync", "-avz"]
    assert rsync_command[-1] == f"{expected_file_remote.rsplit('/', 1)[0]}/"

    scp_command = calls[2][0]
    assert scp_command[:6] == [
        "sshpass",
        "-p",
        "test-password",
        "scp",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    assert scp_command[-1] == expected_file_remote

    assert calls[3][0][6] == expected_remote


def test_subprocess_failure_is_still_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_deploy_module(monkeypatch, server_ip="deploy.example.test", server_user="deploy")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def failing_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))
        raise subprocess.CalledProcessError(23, command)

    monkeypatch.setattr(module.subprocess, "run", failing_run)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        module.main()

    assert caught.value.returncode == 23
    assert len(calls) == 1
    assert calls[0][1] == {"shell": False, "check": True}
