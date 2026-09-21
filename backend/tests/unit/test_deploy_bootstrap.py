"""deploy_server.sh works without a checkout: it downloads the release source first."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy_server.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    # A fake GitHub source archive holding just what the installer needs.
    src = tmp_path / "university-helper-9.9.9"
    (src / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, src / "scripts" / "deploy_server.sh")
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", src / "docker-compose.release.yml")
    shutil.copytree(REPO_ROOT / "database", src / "database")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src, arcname=src.name)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _write_executable(
        bin_dir / "curl",
        f"""
        #!/usr/bin/env bash
        echo "curl $*" >> "{log}"
        out=""; url=""; fmt=""
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -o) out="$2"; shift 2 ;;
            -w) fmt="$2"; shift 2 ;;
            http*) url="$1"; shift ;;
            *) shift ;;
          esac
        done
        case "$url" in
          */archive/refs/tags/*) cp "{archive}" "$out"; exit 0 ;;
          */releases/latest) printf 'https://github.com/sweetcornna/university-helper/releases/tag/v9.9.7'; exit 0 ;;
        esac
        if [[ "$fmt" == *http_code* ]]; then printf '200'; else printf '{{}}'; fi
        """,
    )
    _write_executable(
        bin_dir / "docker",
        f"""
        #!/usr/bin/env bash
        echo "docker $* UH_TAG=${{UH_TAG:-}}" >> "{log}"
        case "$1" in
          --version) echo "Docker version 29.4.1, build test"; exit 0 ;;
          info) exit 0 ;;
          compose) exit 0 ;;
        esac
        exit 1
        """,
    )
    workdir = tmp_path / "work"
    workdir.mkdir()
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env.pop("UH_BOOTSTRAPPED", None)
    return workdir, env, log


def test_standalone_script_downloads_source_and_deploys(sandbox):
    workdir, env, log = sandbox
    shutil.copy2(SCRIPT, workdir / "deploy_server.sh")

    result = subprocess.run(
        ["bash", "deploy_server.sh", "--tag", "v9.9.9", "-y"],
        cwd=workdir, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    install = workdir / "university-helper"
    assert (install / "database" / "00-schema.sql").is_file()
    assert (install / ".env").is_file()
    assert (install / ".uh-source-tag").read_text().strip() == "v9.9.9"
    calls = log.read_text()
    assert "archive/refs/tags/v9.9.9.tar.gz" in calls
    assert "pull UH_TAG=9.9.9" in calls
    assert "Deploy complete." in result.stdout


def test_piped_script_resolves_latest_release(sandbox):
    workdir, env, log = sandbox

    result = subprocess.run(
        ["bash", "-s", "--", "-y"],
        input=SCRIPT.read_text(encoding="utf-8"),
        cwd=workdir, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = log.read_text()
    assert "archive/refs/tags/v9.9.7.tar.gz" in calls
    assert "pull UH_TAG=9.9.7" in calls


def test_release_asset_uses_its_bundled_tag(sandbox):
    workdir, env, log = sandbox
    stamped = SCRIPT.read_text(encoding="utf-8").replace('UH_BUNDLED_TAG=""', 'UH_BUNDLED_TAG="v9.9.8"', 1)
    (workdir / "deploy_server.sh").write_text(stamped, encoding="utf-8")

    result = subprocess.run(
        ["bash", "deploy_server.sh", "-y"],
        cwd=workdir, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "archive/refs/tags/v9.9.8.tar.gz" in log.read_text()


def test_offline_mode_refuses_to_download(sandbox):
    workdir, env, log = sandbox
    shutil.copy2(SCRIPT, workdir / "deploy_server.sh")
    env["UH_DEPLOY_OFFLINE"] = "1"

    result = subprocess.run(
        ["bash", "deploy_server.sh", "-y"],
        cwd=workdir, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode != 0
    assert "UH_DEPLOY_OFFLINE=1" in result.stderr
    assert not log.exists()


def test_existing_env_in_install_dir_is_kept(sandbox):
    workdir, env, _ = sandbox
    shutil.copy2(SCRIPT, workdir / "deploy_server.sh")
    install = workdir / "university-helper"
    install.mkdir()
    (install / ".env").write_text(
        "POSTGRES_PASSWORD=keepme\nSECRET_KEY=" + "s" * 64 + "\nCREDENTIAL_ENCRYPTION_KEY=" + "A" * 43 + "=\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "deploy_server.sh", "--tag", "9.9.9", "-y"],
        cwd=workdir, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "POSTGRES_PASSWORD=keepme" in (install / ".env").read_text()


def test_script_body_runs_only_after_full_download():
    source = SCRIPT.read_text(encoding="utf-8").rstrip()
    assert source.endswith('main "$@"')
    assert "\nmain() {" in source


def _downloaded_install(workdir: Path, tag: str) -> Path:
    install = workdir / "university-helper"
    (install / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, install / "scripts" / "deploy_server.sh")
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", install / "docker-compose.release.yml")
    shutil.copytree(REPO_ROOT / "database", install / "database")
    (install / ".uh-source-tag").write_text(f"{tag}\n", encoding="utf-8")
    (install / ".env").write_text(
        "POSTGRES_PASSWORD=keepme\nSECRET_KEY=" + "s" * 64 + "\nCREDENTIAL_ENCRYPTION_KEY=" + "A" * 43 + "=\n",
        encoding="utf-8",
    )
    return install


def test_update_to_a_new_tag_refreshes_downloaded_source_first(sandbox):
    workdir, env, log = sandbox
    install = _downloaded_install(workdir, "v9.9.0")

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--tag", "9.9.9", "-y"],
        cwd=install, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "from v9.9.0 to v9.9.9" in result.stdout
    assert (install / ".uh-source-tag").read_text().strip() == "v9.9.9"
    assert "POSTGRES_PASSWORD=keepme" in (install / ".env").read_text()
    calls = log.read_text()
    assert calls.count("archive/refs/tags/v9.9.9.tar.gz") == 1
    assert "pull UH_TAG=9.9.9" in calls


def test_rerun_with_the_installed_tag_does_not_download(sandbox):
    workdir, env, log = sandbox
    install = _downloaded_install(workdir, "v9.9.9")

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--tag", "v9.9.9", "-y"],
        cwd=install, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "archive/refs/tags" not in log.read_text()


def test_new_release_asset_run_next_to_old_install_refreshes_it(sandbox):
    workdir, env, log = sandbox
    install = _downloaded_install(workdir, "v9.9.0")
    stamped = SCRIPT.read_text(encoding="utf-8").replace('UH_BUNDLED_TAG=""', 'UH_BUNDLED_TAG="v9.9.8"', 1)

    result = subprocess.run(
        ["bash", "-s", "--", "-y"],
        input=stamped,
        cwd=workdir, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (install / ".uh-source-tag").read_text().strip() == "v9.9.8"
    assert "pull UH_TAG=9.9.8" in log.read_text()


def test_git_checkout_is_not_overwritten_when_tags_differ(sandbox):
    workdir, env, log = sandbox
    checkout = workdir / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "backend").mkdir()
    (checkout / "backend" / "pyproject.toml").write_text('[project]\nversion = "9.9.0"\n', encoding="utf-8")
    shutil.copy2(SCRIPT, checkout / "scripts" / "deploy_server.sh")
    shutil.copy2(REPO_ROOT / "docker-compose.release.yml", checkout / "docker-compose.release.yml")
    shutil.copytree(REPO_ROOT / "database", checkout / "database")

    result = subprocess.run(
        ["bash", "scripts/deploy_server.sh", "--tag", "9.9.9", "-y"],
        cwd=checkout, env=env, text=True, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "git checkout v9.9.9" in result.stdout + result.stderr
    assert "archive/refs/tags" not in log.read_text()
    assert not (checkout / ".uh-source-tag").exists()
