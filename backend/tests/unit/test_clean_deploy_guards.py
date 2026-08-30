"""Guardrails for clean-environment server deployment."""

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _bash_deploy_fixture(tmp_path: Path, script_source: str) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "bash-deploy"
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "deploy_server.sh").write_text(script_source, encoding="utf-8")
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", root / "docker-compose.release.yml")

    bin_dir = root / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "docker",
        """
        #!/usr/bin/env bash
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
        printf '%s' "${FAKE_HEALTH_STATUS:-200}"
        exit 0
        """,
    )
    _write_executable(
        bin_dir / "sleep",
        """
        #!/usr/bin/env bash
        exit 0
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return root, env


def _run_bash_deploy(tmp_path: Path, script_source: str, *, health_status: str) -> subprocess.CompletedProcess[str]:
    root, env = _bash_deploy_fixture(tmp_path, script_source)
    env["FAKE_HEALTH_STATUS"] = health_status
    return subprocess.run(
        ["bash", "scripts/deploy_server.sh", "-y"],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )


def test_deploy_script_accepts_v_prefixed_release_tags(tmp_path):
    """GHCR release images are tagged as 1.4.0, but users often pass v1.4.0."""
    (tmp_path / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "deploy_server.sh", tmp_path / "scripts" / "deploy_server.sh")
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", tmp_path / "docker-compose.release.yml")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"

    _write_executable(
        bin_dir / "docker",
        f"""
        #!/usr/bin/env bash
        echo "$* UH_TAG=${{UH_TAG:-}}" >> {docker_log}
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
        exit 0
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--tag", "v1.4.0", "-y"],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "compose -p university-helper -f docker-compose.release.yml pull UH_TAG=1.4.0" in docker_log.read_text(
        encoding="utf-8"
    )


def test_web_image_healthcheck_uses_ipv4_loopback():
    dockerfile = (REPO_ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    assert "http://127.0.0.1/" in dockerfile
    assert "http://localhost/" not in dockerfile


def test_release_compose_example_uses_publishable_image_tag():
    compose = (REPO_ROOT / "docker-compose.release.yml").read_text(encoding="utf-8")

    assert re.search(r"UH_TAG=\d+\.\d+\.\d+\b", compose)
    assert "UH_TAG=v1." not in compose


def test_bash_health_success_is_zero(tmp_path):
    source = (REPO_ROOT / "scripts" / "deploy_server.sh").read_text(encoding="utf-8")

    result = _run_bash_deploy(tmp_path, source, health_status="200")

    assert result.returncode == 0, result.stdout
    assert "App is healthy." in result.stdout
    assert "Deploy complete." in result.stdout


def test_bash_health_timeout_is_fatal_and_regresses_old_success(tmp_path):
    source = (REPO_ROOT / "scripts" / "deploy_server.sh").read_text(encoding="utf-8")
    legacy_source = source.replace("wait_health\nscaffold_tls", "wait_health || true\nscaffold_tls")
    assert legacy_source != source

    legacy = _run_bash_deploy(tmp_path / "legacy", legacy_source, health_status="503")
    fixed = _run_bash_deploy(tmp_path / "fixed", source, health_status="503")

    assert legacy.returncode == 0, legacy.stdout
    assert "Deploy complete." in legacy.stdout
    assert fixed.returncode != 0, fixed.stdout
    assert "Health check did not pass within 120s." in fixed.stdout
    assert "Deploy complete." not in fixed.stdout


def test_powershell_health_failure_path_is_fatal_static_guard():
    source = (REPO_ROOT / "scripts" / "deploy_server.ps1").read_text(encoding="utf-8")

    assert "StatusCode -ge 200" in source
    assert "StatusCode -lt 300" in source
    assert "never returned a 2xx response" in source
    assert 'Die "Health check timed out or never returned a 2xx response.' in source
    assert 'else { Warn "Health check timed out.' not in source


def _powershell_deploy_fixture(tmp_path: Path, script_source: str) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "powershell-deploy"
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "deploy_server.ps1").write_text(script_source, encoding="utf-8")
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", root / "docker-compose.release.yml")

    bin_dir = root / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "docker",
        """
        #!/usr/bin/env bash
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

    wrapper = root / "run-test.ps1"
    wrapper.write_text(
        textwrap.dedent(
            """
            $ErrorActionPreference = 'Stop'
            function Invoke-WebRequest {
              param(
                [Parameter(Position=0)][string]$Uri,
                [switch]$UseBasicParsing,
                [int]$TimeoutSec
              )
              if ($env:FAKE_HEALTH_STATUS -ne '200') { throw 'fake health failure' }
              [pscustomobject]@{ StatusCode = 200 }
            }
            function Start-Sleep { param([int]$Seconds) }
            & $env:FAKE_DEPLOY_SCRIPT -Yes
            """
        ).lstrip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_DEPLOY_SCRIPT"] = str(scripts_dir / "deploy_server.ps1")
    return wrapper, env


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh unavailable; static PowerShell guard covers this host")
def test_powershell_health_success_and_timeout_are_consistent(tmp_path):
    source = (REPO_ROOT / "scripts" / "deploy_server.ps1").read_text(encoding="utf-8")
    legacy_source = source.replace(
        'Die "Health check timed out or never returned a 2xx response. Check: docker compose -p $Project -f $ComposeFile logs --tail=80 app"',
        'Warn "Health check timed out. Check: docker compose -p $Project -f $ComposeFile logs --tail=80 app"',
    )
    assert legacy_source != source

    success_wrapper, success_env = _powershell_deploy_fixture(tmp_path / "success", source)
    success_env["FAKE_HEALTH_STATUS"] = "200"
    success = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(success_wrapper)],
        cwd=success_wrapper.parent,
        env=success_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    timeout_wrapper, timeout_env = _powershell_deploy_fixture(tmp_path / "timeout", source)
    timeout_env["FAKE_HEALTH_STATUS"] = "503"
    timeout = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(timeout_wrapper)],
        cwd=timeout_wrapper.parent,
        env=timeout_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    legacy_wrapper, legacy_env = _powershell_deploy_fixture(tmp_path / "legacy", legacy_source)
    legacy_env["FAKE_HEALTH_STATUS"] = "503"
    legacy = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(legacy_wrapper)],
        cwd=legacy_wrapper.parent,
        env=legacy_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert success.returncode == 0, success.stdout
    assert "Deploy complete." in success.stdout
    assert timeout.returncode != 0, timeout.stdout
    assert "Deploy complete." not in timeout.stdout
    assert legacy.returncode == 0, legacy.stdout
    assert "Deploy complete." in legacy.stdout
