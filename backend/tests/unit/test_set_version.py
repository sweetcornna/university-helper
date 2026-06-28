"""scripts/set_version.sh stamps ONE version into all release manifests, idempotently.

Self-contained: synthesizes minimal fixtures for all release files (including the
Tauri files that workstream E owns) so this test is green regardless of E's state.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "set_version.sh"

PKG_JSON = (
    "{\n"
    '  "name": "university-helper-frontend",\n'
    '  "private": true,\n'
    '  "version": "0.0.0",\n'
    '  "dependencies": { "react": "^18.2.0", "jsqr": "^1.4.0" }\n'
    "}\n"
)
PKG_LOCK = (
    "{\n"
    '  "name": "university-helper-frontend",\n'
    '  "version": "0.0.0",\n'
    '  "lockfileVersion": 3,\n'
    '  "requires": true,\n'
    '  "packages": {\n'
    '    "": {\n'
    '      "name": "university-helper-frontend",\n'
    '      "version": "0.0.0",\n'
    '      "dependencies": { "react": "^18.2.0", "jsqr": "^1.4.0" }\n'
    "    },\n"
    '    "node_modules/jsqr": { "version": "1.4.0" }\n'
    "  }\n"
    "}\n"
)
PYPROJECT = (
    "[project]\n"
    'name = "university-helper-backend"\n'
    'version = "0.0.0"\n'
    'requires-python = ">=3.11"\n\n'
    "[tool.ruff]\n"
    'target-version = "py311"\n'
)
MAIN_PY = (
    "app = FastAPI(\n"
    '    title="University Helper API",\n'
    '    description="…",\n'
    '    version="0.0.0",\n'
    '    docs_url="/docs",\n'
    ")\n"
)
TAURI_JSON = (
    "{\n"
    '  "productName": "University Helper",\n'
    '  "version": "0.0.0",\n'
    '  "identifier": "xyz.cornna.shuake"\n'
    "}\n"
)
CARGO_TOML = (
    "[package]\n"
    'name = "uh"\n'
    'version = "0.0.0"\n'
    'edition = "2021"\n\n'
    "[dependencies]\n"
    'tauri = { version = "2", features = [] }\n'
)

FILES = [
    "frontend/package.json",
    "frontend/package-lock.json",
    "backend/pyproject.toml",
    "backend/app/main.py",
    "frontend/src-tauri/tauri.conf.json",
    "frontend/src-tauri/Cargo.toml",
]


def _make_tree(tmp: Path) -> None:
    (tmp / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp / "scripts" / "set_version.sh")
    (tmp / "frontend" / "src-tauri").mkdir(parents=True)
    (tmp / "backend" / "app").mkdir(parents=True)
    (tmp / "frontend" / "package.json").write_text(PKG_JSON)
    (tmp / "frontend" / "package-lock.json").write_text(PKG_LOCK)
    (tmp / "backend" / "pyproject.toml").write_text(PYPROJECT)
    (tmp / "backend" / "app" / "main.py").write_text(MAIN_PY)
    (tmp / "frontend" / "src-tauri" / "tauri.conf.json").write_text(TAURI_JSON)
    (tmp / "frontend" / "src-tauri" / "Cargo.toml").write_text(CARGO_TOML)


def _run(tmp: Path, version: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(tmp / "scripts" / "set_version.sh"), version],
        check=True,
        capture_output=True,
        text=True,
    )


def test_stamps_all_release_manifests(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "9.9.9")
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == "9.9.9"
    package_lock = json.loads((tmp_path / "frontend/package-lock.json").read_text())
    assert package_lock["version"] == "9.9.9"
    assert package_lock["packages"][""]["version"] == "9.9.9"
    assert 'version = "9.9.9"' in (tmp_path / "backend/pyproject.toml").read_text()
    assert 'version="9.9.9"' in (tmp_path / "backend/app/main.py").read_text()
    assert json.loads((tmp_path / "frontend/src-tauri/tauri.conf.json").read_text())["version"] == "9.9.9"
    assert 'version = "9.9.9"' in (tmp_path / "frontend/src-tauri/Cargo.toml").read_text()


def test_does_not_touch_dependency_versions(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "9.9.9")
    cargo = (tmp_path / "frontend/src-tauri/Cargo.toml").read_text()
    assert 'tauri = { version = "2"' in cargo  # dep spec untouched
    pkg = json.loads((tmp_path / "frontend/package.json").read_text())
    assert pkg["dependencies"]["react"] == "^18.2.0"  # dep spec untouched
    package_lock = json.loads((tmp_path / "frontend/package-lock.json").read_text())
    assert package_lock["packages"]["node_modules/jsqr"]["version"] == "1.4.0"


def test_strips_leading_v(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "v1.4.0")
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == "1.4.0"


def test_idempotent(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "9.9.9")
    snap = {f: (tmp_path / f).read_text() for f in FILES}
    _run(tmp_path, "9.9.9")  # second run must be a no-op
    for f in FILES:
        assert (tmp_path / f).read_text() == snap[f], f"{f} changed on re-run"


def test_rejects_garbage_version(tmp_path):
    _make_tree(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _run(tmp_path, "not-a-version")
