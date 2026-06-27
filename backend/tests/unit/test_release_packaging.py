"""Release packaging guardrails for the desktop CI workflow."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_CONFIG = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _tauri_config() -> dict:
    return json.loads(TAURI_CONFIG.read_text())


def _clean_yaml_value(value: str) -> str:
    return value.split("#", 1)[0].strip().strip("\"'")


def _desktop_matrix_entries() -> list[dict[str, str]]:
    lines = RELEASE_WORKFLOW.read_text().splitlines()
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_desktop_job = False
    in_matrix_include = False

    for line in lines:
        stripped = line.strip()

        if line.startswith("  desktop:"):
            in_desktop_job = True
            continue

        if in_desktop_job and line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            break

        if not in_desktop_job:
            continue

        if stripped == "include:":
            in_matrix_include = True
            continue

        if not in_matrix_include:
            continue

        if stripped.startswith("- "):
            if current is not None:
                entries.append(current)
            current = {}
            item = stripped[2:]
            if ":" in item:
                key, value = item.split(":", 1)
                current[key.strip()] = _clean_yaml_value(value)
            continue

        if current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = _clean_yaml_value(value)

    if current is not None:
        entries.append(current)

    return entries


def _tauri_action_env_keys() -> set[str]:
    lines = RELEASE_WORKFLOW.read_text().splitlines()
    action_index = next(i for i, line in enumerate(lines) if line.strip() == "uses: tauri-apps/tauri-action@v0")
    step_lines: list[str] = []

    for line in lines[action_index + 1 :]:
        if line.startswith("      - "):
            break
        step_lines.append(line)

    env_keys: set[str] = set()
    in_env = False
    for line in step_lines:
        if line.startswith("        env:"):
            in_env = True
            continue

        if in_env and line.startswith("        ") and not line.startswith("          "):
            break

        if in_env and line.startswith("          ") and ":" in line:
            key = line.strip().split(":", 1)[0]
            if not key.startswith("#"):
                env_keys.add(key)

    return env_keys


def test_windows_msi_uses_chinese_wix_language_for_chinese_product_name():
    config = _tauri_config()

    assert any(ord(ch) > 127 for ch in config["productName"])
    assert "msi" in config["bundle"]["targets"]
    assert config["bundle"].get("windows", {}).get("wix", {}).get("language") == "zh-CN"


def test_macos_unsigned_builds_use_ad_hoc_signing_identity():
    config = _tauri_config()

    assert config["bundle"].get("macOS", {}).get("signingIdentity") == "-"


def test_release_workflow_does_not_pass_empty_apple_certificate_env_to_unsigned_builds():
    disallowed_env_keys = {
        "APPLE_CERTIFICATE",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_SIGNING_IDENTITY",
        "APPLE_ID",
        "APPLE_PASSWORD",
        "APPLE_TEAM_ID",
    }

    assert _tauri_action_env_keys().isdisjoint(disallowed_env_keys)


def test_release_workflow_pairs_intel_target_with_supported_intel_macos_runner_label():
    entries = _desktop_matrix_entries()

    assert all(entry.get("os") != "macos-13" for entry in entries)
    assert [entry.get("os") for entry in entries if entry.get("rust_target") == "x86_64-apple-darwin"] == [
        "macos-15-intel"
    ]
