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


CARGO_TOML = TAURI_DIR / "Cargo.toml"
NSIS_HOOKS = TAURI_DIR / "windows" / "hooks.nsh"


def _update_flow() -> str:
    source = LIB_RS.read_text()
    return source[source.index("async fn check_for_updates") : source.index("#[cfg(test)]")]


def test_updater_asks_before_installing():
    flow = _update_flow()

    assert "OkCancelCustom" in flow
    assert '"现在更新"' in flow and '"稍后"' in flow
    assert flow.index("blocking_show()") < flow.index(".download_and_install(")
    assert "if !accepted" in flow


def test_updater_stops_the_sidecar_before_the_process_exits():
    flow = _update_flow()

    assert ".timeout(UPDATE_CHECK_TIMEOUT)" in flow
    hook = flow[flow.index(".on_before_exit(") : flow.index(".build()")]
    assert "kill_sidecar" in hook
    assert "cleanup_before_exit()" in hook


def test_sidecar_is_told_which_process_owns_it():
    source = LIB_RS.read_text()

    assert 'command.env("UH_PARENT_PID", std::process::id().to_string())' in source
    assert "fn stop_process_tree" in source
    assert '"/T", "/F"' in source
    assert "libc::SIGTERM" in source


def test_dialog_plugin_is_registered():
    assert 'tauri-plugin-dialog = "2"' in CARGO_TOML.read_text()
    assert ".plugin(tauri_plugin_dialog::init())" in LIB_RS.read_text()


def test_desktop_errors_are_written_to_a_log_file():
    source = LIB_RS.read_text()

    assert "app_log_dir()" in source
    assert 'LOG_FILE_NAME: &str = "desktop.log"' in source
    assert "eprintln!" not in _update_flow()


def test_nsis_installer_stops_running_backend_before_copying_files():
    config = json.loads(TAURI_CONFIG.read_text())
    hooks_path = config["bundle"]["windows"]["nsis"]["installerHooks"]
    hooks = (TAURI_DIR / hooks_path).read_text(encoding="ascii")

    assert (TAURI_DIR / hooks_path).resolve() == NSIS_HOOKS.resolve()
    preinstall = hooks[hooks.index("!macro NSIS_HOOK_PREINSTALL") : hooks.index("!macroend")]
    assert "taskkill.exe" in preinstall
    assert "/IM uh-backend.exe" in preinstall
