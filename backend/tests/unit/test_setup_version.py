"""Guard the setup banner against drifting from the stamped release version."""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup.sh"
README_DOCS = (REPO_ROOT / "README.md", REPO_ROOT / "README.zh-CN.md")


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _make_setup_fixture(tmp_path: Path, version: str) -> Path:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / ".env.example").write_text("SECRET_KEY=test\n")
    (tmp_path / "frontend" / "package.json").write_text(
        json.dumps({"name": "university-helper-frontend", "version": version}, indent=2) + "\n"
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        "#!/bin/sh\n" 'if [ "$1" = compose ] && [ "$2" = version ]; then exit 0; fi\n' "exit 0\n",
    )
    _write_executable(fake_bin / "npm", "#!/bin/sh\nexit 0\n")
    shutil.copy(SETUP_SCRIPT, tmp_path / "scripts" / "setup.sh")
    return fake_bin


def _run_setup(tmp_path: Path, fake_bin: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(tmp_path / "scripts" / "setup.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_setup_banner_tracks_the_stamped_frontend_manifest_version(tmp_path):
    fake_bin = _make_setup_fixture(tmp_path, "9.8.7")

    first = _run_setup(tmp_path, fake_bin)
    assert first.returncode == 0, first.stderr
    assert "=== university-helper · local setup (v9.8.7) ===" in first.stdout

    package_json = tmp_path / "frontend" / "package.json"
    package_json.write_text(
        json.dumps({"name": "university-helper-frontend", "version": "2.0.0-beta.1"}, indent=2) + "\n"
    )
    second = _run_setup(tmp_path, fake_bin)
    assert second.returncode == 0, second.stderr
    assert "=== university-helper · local setup (v2.0.0-beta.1) ===" in second.stdout


def test_setup_fails_when_the_canonical_version_is_missing(tmp_path):
    fake_bin = _make_setup_fixture(tmp_path, "9.8.7")
    (tmp_path / "frontend" / "package.json").write_text(
        json.dumps({"name": "university-helper-frontend"}, indent=2) + "\n"
    )

    result = _run_setup(tmp_path, fake_bin)

    assert result.returncode == 1
    assert "could not read release version from frontend/package.json" in result.stderr


def test_setup_creates_env_with_private_mode_under_permissive_umask(tmp_path):
    fake_bin = _make_setup_fixture(tmp_path, "9.8.7")
    previous_umask = os.umask(0o022)
    try:
        result = _run_setup(tmp_path, fake_bin)
    finally:
        os.umask(previous_umask)

    assert result.returncode == 0, result.stderr
    env_path = tmp_path / ".env"
    assert env_path.read_text() == (tmp_path / ".env.example").read_text()
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_setup_preserves_existing_env_content_and_mode(tmp_path):
    fake_bin = _make_setup_fixture(tmp_path, "9.8.7")
    env_path = tmp_path / ".env"
    original = "SECRET_KEY=already-configured\n"
    env_path.write_text(original)
    env_path.chmod(0o640)

    previous_umask = os.umask(0o022)
    try:
        result = _run_setup(tmp_path, fake_bin)
    finally:
        os.umask(previous_umask)

    assert result.returncode == 0, result.stderr
    assert env_path.read_text() == original
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o640


def test_readmes_use_private_env_creation_commands():
    bare_copy = re.compile(r"(?m)^[ \t]*cp[ \t]+\.env\.example[ \t]+\.env(?:[ \t#]|$)")

    for readme in README_DOCS:
        document = readme.read_text(encoding="utf-8")
        assert not bare_copy.search(document), f"{readme} must not document a bare .env copy"
        assert "install -m 600 .env.example .env" in document
