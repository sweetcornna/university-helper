"""Release packaging guardrails for the desktop CI workflow."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TAURI_CONFIG = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
ACTIVE_WORKFLOW_SUFFIXES = {".yml", ".yaml"}
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ACTIVE_PIP_BUILD_CONFIGS = (
    REPO_ROOT / "Dockerfile.server",
    REPO_ROOT / ".github" / "workflows" / "test.yml",
    RELEASE_WORKFLOW,
)


def _tauri_config() -> dict:
    return json.loads(TAURI_CONFIG.read_text())


def _clean_yaml_value(value: str) -> str:
    return value.split("#", 1)[0].strip().strip("\"'")


def _workflow_text() -> str:
    return RELEASE_WORKFLOW.read_text()


def test_active_pip_build_configs_keep_tls_verification_enabled():
    forbidden_tokens = ("PIP_TRUSTED_HOST", "trusted-host", "--trusted-host")
    index_url_pattern = re.compile(r"\bPIP_INDEX_URL\s*[:=]\s*(https?://[^\s\\|'\"]+)")

    for config_path in ACTIVE_PIP_BUILD_CONFIGS:
        config_text = config_path.read_text()
        for token in forbidden_tokens:
            assert token not in config_text, f"{token} present in {config_path}"

        index_urls = index_url_pattern.findall(config_text)
        assert index_urls, f"no static PIP_INDEX_URL found in {config_path}"
        assert all(url.startswith("https://") for url in index_urls), config_path


def test_server_runtime_does_not_persist_pip_index_url():
    dockerfile = (REPO_ROOT / "Dockerfile.server").read_text()
    runtime = dockerfile.split("# ---------- runtime ----------", 1)[1]

    assert "PIP_INDEX_URL" not in runtime
    assert "PIP_NO_INDEX=1" in runtime
    assert "--no-index" in runtime
    assert "apt-mirror-selection" in runtime


def _workflow_lines() -> list[str]:
    return _workflow_text().splitlines()


def _workflow_run_blocks() -> list[tuple[str, str, str]]:
    """Return every workflow run block as (job, step, shell script)."""
    lines = _workflow_lines()
    in_jobs = False
    job_name = ""
    step_name = ""
    blocks: list[tuple[str, str, str]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped == "jobs:":
            in_jobs = True
            index += 1
            continue

        if not in_jobs:
            index += 1
            continue

        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            job_name = stripped[:-1]
            step_name = ""
            index += 1
            continue

        if line.startswith("      - "):
            step_name = stripped[2:]
            if step_name.startswith("name: "):
                step_name = step_name[6:]
            index += 1
            continue

        if line.startswith("        run:"):
            raw_run = line.split(":", 1)[1].strip()
            if raw_run in {"|", "|-", "|+", ">", ">-", ">+"}:
                body: list[str] = []
                index += 1
                while index < len(lines):
                    body_line = lines[index]
                    if body_line.startswith("          "):
                        body.append(body_line[10:])
                    elif body_line == "":
                        body.append("")
                    else:
                        break
                    index += 1
                raw_run = "\n".join(body)
                blocks.append((job_name, step_name, raw_run))
                continue

            blocks.append((job_name, step_name, raw_run))

        index += 1

    return blocks


def _workflow_run_block(job_name: str, step_name: str) -> str:
    for job, step, script in _workflow_run_blocks():
        if job == job_name and step == step_name:
            return script
    raise AssertionError(f"run block not found: {job_name}/{step_name}")


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
    action_index = next(
        i
        for i, line in enumerate(lines)
        if re.match(r"^\s*uses: tauri-apps/tauri-action@[0-9a-f]{40}\s+# v0$", line)
    )
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


def _workflow_external_uses() -> list[tuple[Path, int, str]]:
    """Return active workflow action references, excluding local ``./`` uses."""
    use_pattern = re.compile(r"^(?:-\s+)?uses:\s*(?P<action>[^#\s]+)")
    references: list[tuple[Path, int, str]] = []

    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_path.is_file() or workflow_path.suffix not in ACTIVE_WORKFLOW_SUFFIXES:
            continue
        for line_number, line in enumerate(workflow_path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            match = use_pattern.match(line.strip())
            if match is None:
                continue
            action = match.group("action")
            if action.startswith("./"):
                continue
            references.append((workflow_path, line_number, action))

    return references


def _assert_pinned_external_use(action: str, source: str) -> None:
    """Require an external workflow action to use a lowercase, full commit SHA."""
    owner_repo, separator, ref = action.rpartition("@")
    assert separator and owner_repo and ref, f"{source}: malformed external action reference {action!r}"
    assert FULL_SHA_RE.fullmatch(ref), (
        f"{source}: external action {action!r} must be pinned to a 40-character lowercase commit SHA"
    )


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


def test_release_workflow_run_blocks_do_not_interpolate_github_expressions():
    blocks = _workflow_run_blocks()

    assert len(blocks) == 16
    for job_name, step_name, script in blocks:
        assert "${{" not in script, f"direct GitHub expression in {job_name}/{step_name}"


def test_active_workflow_actions_are_pinned_to_full_lowercase_shas():
    references = _workflow_external_uses()

    assert references, "no external workflow actions found"
    for workflow_path, line_number, action in references:
        _assert_pinned_external_use(action, f"{workflow_path}:{line_number}")


@pytest.mark.parametrize("mutable_ref", ["master", "v4"])
def test_mutable_workflow_action_refs_are_rejected(mutable_ref):
    with pytest.raises(AssertionError, match="40-character lowercase commit SHA"):
        _assert_pinned_external_use(f"actions/checkout@{mutable_ref}", "fixture")


def test_release_tag_is_env_mapped_and_shell_metacharacters_are_rejected(tmp_path):
    resolver_steps = (
        ("create-release", "Resolve version from tag"),
        ("app-image", "Resolve version"),
        ("web-image", "Resolve version"),
    )
    expected_env = "RELEASE_REF: ${{ github.event.inputs.tag || github.ref_name }}"

    for job_name, step_name in resolver_steps:
        step = _step_block(job_name, step_name)
        assert expected_env in step
        script = _workflow_run_block(job_name, step_name)
        assert 'REF="$RELEASE_REF"' in script
        assert 'if [[ ! "$REF" =~ ' in script

        valid_output = tmp_path / f"{job_name}-valid-output"
        valid_env = os.environ.copy()
        valid_env.update(RELEASE_REF="v1.4.5-rc.1", GITHUB_OUTPUT=str(valid_output))
        valid = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True, env=valid_env
        )
        assert valid.returncode == 0, valid.stderr
        assert valid_output.read_text() == "tag=v1.4.5-rc.1\nversion=1.4.5-rc.1\n"

        marker = tmp_path / f"{job_name}-injected"
        malicious_output = tmp_path / f"{job_name}-malicious-output"
        malicious = f'v1.4.0"; touch {marker}; #\n'
        malicious_env = os.environ.copy()
        malicious_env.update(RELEASE_REF=malicious, GITHUB_OUTPUT=str(malicious_output))
        rejected = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True, env=malicious_env
        )
        assert rejected.returncode == 2, rejected.stderr
        assert not marker.exists()
        assert not malicious_output.exists()
