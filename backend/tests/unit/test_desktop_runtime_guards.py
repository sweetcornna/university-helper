"""Desktop runtime guardrails for crash-prone startup paths."""

import json
import plistlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_DIR = REPO_ROOT / "frontend" / "src-tauri"
LIB_RS = TAURI_DIR / "src" / "lib.rs"
TAURI_CONFIG = TAURI_DIR / "tauri.conf.json"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def test_rust_sidecar_uses_tauri_v2_filename_not_external_bin_path():
    source = LIB_RS.read_text()

    assert '.sidecar("uh-backend")' in source
    assert '.sidecar("binaries/uh-backend")' not in source


def test_desktop_startup_path_does_not_abort_on_recoverable_errors():
    source = LIB_RS.read_text()

    assert ".expect(" not in source
    assert ".unwrap()" not in source
    assert "本地后端在启动完成前退出" in source


def test_macos_pyinstaller_sidecar_can_load_embedded_python_under_runtime_signing():
    config = json.loads(TAURI_CONFIG.read_text())
    macos = config["bundle"]["macOS"]
    entitlements_path = TAURI_DIR / macos["entitlements"]

    assert macos["hardenedRuntime"] is True
    with entitlements_path.open("rb") as handle:
        entitlements = plistlib.load(handle)

    assert entitlements["com.apple.security.cs.disable-library-validation"] is True


def test_release_workflow_smoke_tests_signed_macos_sidecar_after_bundling():
    workflow = RELEASE_WORKFLOW.read_text()

    assert "Smoke-test signed macOS sidecar" in workflow
    assert "bundle/macos/学道.app/Contents/MacOS/uh-backend" in workflow
    assert "scripts/smoke_sidecar.sh" in workflow
