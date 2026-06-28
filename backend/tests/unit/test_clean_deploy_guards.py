"""Guardrails for clean-environment server deployment."""

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


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
