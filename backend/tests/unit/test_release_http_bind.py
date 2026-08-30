"""Regression tests for the release stack's public HTTP bind contract."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASH_DEPLOY = REPO_ROOT / "scripts" / "deploy_server.sh"
POWERSHELL_DEPLOY = REPO_ROOT / "scripts" / "deploy_server.ps1"
COMPOSE_FILE = REPO_ROOT / "docker-compose.release.yml"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _bash_deploy_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / "deploy"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(BASH_DEPLOY, scripts / BASH_DEPLOY.name)
    shutil.copy2(COMPOSE_FILE, root / COMPOSE_FILE.name)

    bin_dir = root / "bin"
    bin_dir.mkdir()
    docker_log = root / "docker.log"
    _write_executable(
        bin_dir / "docker",
        f"""
        #!/usr/bin/env bash
        printf '%s HTTP_BIND_HOST=%s\\n' "$*" "${{HTTP_BIND_HOST:-}}" >> "{docker_log}"
        if [[ "$1" == "--version" ]]; then
          echo "Docker version 29.4.1, build test"
          exit 0
        fi
        if [[ "$1" == "info" ]]; then
          exit 0
        fi
        if [[ "$1" == "compose" && "$2" == "version" ]]; then
          echo "Docker Compose version v2.32.0"
          exit 0
        fi
        if [[ "$1" == "compose" ]]; then
          exit 0
        fi
        exit 1
        """,
    )
    _write_executable(
        bin_dir / "curl",
        """
        #!/usr/bin/env bash
        printf '200'
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return root, env, docker_log


@pytest.mark.parametrize(
    ("args", "expected_bind"),
    [
        (("-y", "--no-tls"), "127.0.0.1"),
        (("--domain", "example.test", "-y", "--no-tls"), "127.0.0.1"),
        (("--host", "203.0.113.10", "-y", "--no-tls"), "0.0.0.0"),
    ],
)
def test_bash_deploy_persists_and_passes_expected_http_bind_host(tmp_path, args, expected_bind):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    up_lines = [line for line in docker_log.read_text().splitlines() if " up -d " in f" {line} "]
    assert len(up_lines) == 1
    assert f"HTTP_BIND_HOST={expected_bind}" in up_lines[0]
    env_path = root / ".env"
    assert f"HTTP_BIND_HOST={expected_bind}\n" in env_path.read_text()
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "domain",
    [
        "../../nginx/nginx",
        "example\n.com",
        "example..com",
        "-example.com",
        "example-.com",
        "a" * 64 + ".example.com",
        ".".join(["a" * 63] * 4),
        "example_com",
        "",
    ],
    ids=[
        "path-traversal",
        "control-character",
        "empty-label",
        "leading-hyphen",
        "trailing-hyphen",
        "label-too-long",
        "domain-too-long",
        "invalid-character",
        "empty-domain",
    ],
)
def test_bash_deploy_rejects_invalid_domain_before_side_effects(tmp_path, domain):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    target = root / "nginx" / "nginx.conf"
    target.parent.mkdir()
    original = "keep this configuration\n"
    target.write_text(original, encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain", domain, "-y"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid --domain" in result.stderr
    if domain:
        assert domain not in result.stderr
    assert not docker_log.exists()
    assert not (root / "deploy").exists()
    assert not (root / ".env").exists()
    assert target.read_text(encoding="utf-8") == original


def test_bash_deploy_rejects_missing_domain_value_before_side_effects(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid --domain" in result.stderr
    assert not docker_log.exists()
    assert not (root / "deploy").exists()
    assert not (root / ".env").exists()


@pytest.mark.parametrize("domain", ["example.com", "sub.example.com", "xn--fiqs8s.com"])
def test_bash_deploy_accepts_ascii_and_punycode_fqdns(tmp_path, domain):
    root, env, _ = _bash_deploy_fixture(tmp_path)
    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain", domain, "-y", "--no-tls"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f'CORS_ORIGINS=["https://{domain}"]' in (root / ".env").read_text(encoding="utf-8")


def test_bash_deploy_keeps_existing_env_untouched(tmp_path):
    root, env, docker_log = _bash_deploy_fixture(tmp_path)
    env_path = root / ".env"
    original = "SECRET_KEY=existing\nHTTP_BIND_HOST=198.51.100.7\n"
    env_path.write_text(original, encoding="utf-8")
    env_path.chmod(0o640)

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--domain", "example.test", "-y", "--no-tls"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert env_path.read_text(encoding="utf-8") == original
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o640
    up_lines = [line for line in docker_log.read_text().splitlines() if " up -d " in f" {line} "]
    assert len(up_lines) == 1
    assert "HTTP_BIND_HOST=127.0.0.1" in up_lines[0]


def test_bash_and_powershell_bind_modes_match_and_tls_proxy_stays_loopback():
    bash = BASH_DEPLOY.read_text(encoding="utf-8")
    powershell = POWERSHELL_DEPLOY.read_text(encoding="utf-8")

    assert 'HTTP_BIND_HOST="127.0.0.1"' in bash
    assert 'if [[ -n "$HOST_IP" && -z "$DOMAIN" ]]; then' in bash
    assert 'HTTP_BIND_HOST="0.0.0.0"' in bash
    assert 'HTTP_BIND_HOST="$HTTP_BIND_HOST" HTTP_PORT=' in bash
    assert "proxy_pass http://127.0.0.1:${HTTP_PORT};" in bash

    assert re.search(
        r'\$HttpBindHost = if \(\$HostIp -and -not \$Domain\) \{ "0\.0\.0\.0" \} ' r'else \{ "127\.0\.0\.1" \}',
        powershell,
    )
    assert "HTTP_BIND_HOST=$HttpBindHost" in powershell
    assert "$env:HTTP_BIND_HOST = $HttpBindHost" in powershell
