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


def _workflow_text() -> str:
    return RELEASE_WORKFLOW.read_text()


def _workflow_lines() -> list[str]:
    return _workflow_text().splitlines()


def _job_names() -> set[str]:
    lines = _workflow_lines()
    in_jobs = False
    names: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if stripped == "jobs:":
            in_jobs = True
            continue

        if not in_jobs:
            continue

        if line and not line.startswith(" "):
            break

        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            names.add(stripped[:-1])

    return names


def _job_block(job_name: str) -> str:
    lines = _workflow_lines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"  {job_name}:"))
    block = [lines[start]]

    for line in lines[start + 1 :]:
        stripped = line.strip()
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            break
        block.append(line)

    return "\n".join(block)


def _step_block(job_name: str, step_name: str) -> str:
    lines = _job_block(job_name).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {step_name}")
    block = [lines[start]]

    for line in lines[start + 1 :]:
        if line.startswith("      - "):
            break
        block.append(line)

    return "\n".join(block)


def _job_needs(job_name: str) -> set[str]:
    for line in _job_block(job_name).splitlines():
        stripped = line.strip()
        if stripped.startswith("needs:"):
            raw = stripped.split(":", 1)[1].strip()
            if raw.startswith("[") and raw.endswith("]"):
                return {value.strip() for value in raw[1:-1].split(",") if value.strip()}
            return {_clean_yaml_value(raw)}

    return set()


def _desktop_matrix_entries() -> list[dict[str, str]]:
    lines = _workflow_lines()
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


def test_release_notes_include_macos_quarantine_bypass_for_unsigned_builds():
    workflow = _workflow_text()

    assert "xattr -dr com.apple.quarantine" in workflow
    assert '"/Applications/学道.app"' in workflow


def test_release_workflow_pairs_intel_target_with_supported_intel_macos_runner_label():
    entries = _desktop_matrix_entries()

    assert all(entry.get("os") != "macos-13" for entry in entries)
    assert [entry.get("os") for entry in entries if entry.get("rust_target") == "x86_64-apple-darwin"] == [
        "macos-15-intel"
    ]


def test_release_workflow_builds_release_images_in_independent_timeout_bounded_jobs():
    jobs = _job_names()

    assert "images" not in jobs
    assert {"app-image", "web-image"}.issubset(jobs)

    app_job = _job_block("app-image")
    web_job = _job_block("web-image")

    assert "timeout-minutes:" in app_job
    assert "timeout-minutes:" in web_job
    assert "Build & push app image" in app_job
    assert "Build & push web image" not in app_job
    assert "Build & push web image" in web_job
    assert "Build & push app image" not in web_job


def test_release_publish_job_waits_for_both_release_image_jobs():
    assert _job_needs("publish") == {"create-release", "app-image", "web-image", "desktop"}


def test_web_release_image_build_does_not_export_github_actions_cache():
    web_step = _step_block("web-image", "Build & push web image")

    assert "cache-to: type=gha" not in web_step
    assert "${{ env.WEB_IMAGE }}:${{ steps.meta.outputs.version }}" in web_step
    assert "${{ env.WEB_IMAGE }}:latest" in web_step


def test_release_workflow_grants_package_write_only_to_image_jobs():
    workflow = _workflow_text()

    assert "permissions:\n  contents: read" in workflow
    assert "permissions:\n  contents: write\n  packages: write" not in workflow
    assert "packages: write" in _job_block("app-image")
    assert "packages: write" in _job_block("web-image")
    assert "packages: write" not in _job_block("create-release")
    assert "packages: write" not in _job_block("desktop")
    assert "packages: write" not in _job_block("publish")


def test_release_workflow_dispatch_checkouts_use_requested_release_ref():
    workflow = _workflow_text()

    assert workflow.count("ref: ${{ github.event.inputs.tag || github.ref }}") >= 4
