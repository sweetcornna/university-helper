"""Keep desktop updater documentation aligned with the release workflow."""

import os
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _desktop_step(step_name: str) -> dict:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["desktop"]["steps"]
    return next(step for step in steps if step.get("name") == step_name)


def test_readme_describes_workflow_conditional_updater_artifacts():
    signing = _desktop_step("Resolve signing availability")
    bundle = _desktop_step("Build & upload Tauri bundles")
    signing_script = signing["run"]
    bundle_args = bundle["with"]["args"]

    assert signing["env"]["SIGN_KEY"] == "${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}"
    assert 'if [ -n "$SIGN_KEY" ]' in signing_script
    assert 'echo "updater=true"' in signing_script
    assert 'echo "updater=false"' in signing_script
    assert "steps.signing.outputs.updater == 'false'" in bundle_args
    assert '"createUpdaterArtifacts":false' in bundle_args

    readme = " ".join(README.read_text(encoding="utf-8").split())
    assert re.search(
        r"Signed updater artifacts and automatic updates are available only .*" r"Tauri signing secret is configured",
        readme,
    )
    assert re.search(
        r"without it, installers still build but the release omits updater artifacts",
        readme,
    )


def _job(job_name: str) -> dict:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"][job_name]


def _job_step(job_name: str, step_name: str) -> dict:
    return next(step for step in _job(job_name)["steps"] if step.get("name") == step_name)


def _run_signing_gate(tmp_path, *, sign_key: str, repository: str) -> tuple[subprocess.CompletedProcess, str]:
    step = _job_step("create-release", "Require the updater signing key upstream")
    output = tmp_path / f"output-{len(sign_key)}-{repository.replace('/', '_')}"
    env = os.environ.copy()
    env.update(SIGN_KEY=sign_key, REPOSITORY=repository, GITHUB_OUTPUT=str(output))
    result = subprocess.run(["bash"], input=step["run"], text=True, capture_output=True, env=env, check=False)
    return result, output.read_text() if output.exists() else ""


def test_upstream_release_fails_early_without_the_signing_key(tmp_path):
    step = _job_step("create-release", "Require the updater signing key upstream")
    assert step["env"]["SIGN_KEY"] == "${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}"
    assert _job("create-release")["outputs"]["updater"] == "${{ steps.signing.outputs.updater }}"

    signed, signed_output = _run_signing_gate(tmp_path, sign_key="secret", repository="sweetcornna/university-helper")
    assert signed.returncode == 0, signed.stderr
    assert signed_output == "updater=true\n"

    upstream, upstream_output = _run_signing_gate(tmp_path, sign_key="", repository="sweetcornna/university-helper")
    assert upstream.returncode == 1
    assert "TAURI_SIGNING_PRIVATE_KEY is not set" in upstream.stdout
    assert upstream_output == ""

    fork, fork_output = _run_signing_gate(tmp_path, sign_key="", repository="someone/university-helper")
    assert fork.returncode == 0, fork.stderr
    assert fork_output == "updater=false\n"


def test_desktop_assets_get_ascii_names_and_no_per_job_latest_json():
    bundle = _desktop_step("Build & upload Tauri bundles")
    pattern = bundle["with"]["assetNamePattern"]

    assert pattern == "xuedao_[version]_[platform]_[arch][setup][ext]"
    assert pattern.isascii()
    assert bundle["with"]["includeUpdaterJson"] is False


def test_single_updater_manifest_job_gates_promotion_and_publish():
    manifest_job = _job("updater-manifest")
    assemble = _job_step("updater-manifest", "Assemble, verify and upload latest.json")

    assert set(manifest_job["needs"]) == {"create-release", "desktop"}
    assert manifest_job["permissions"] == {"contents": "write"}
    assert "scripts/updater_manifest.py assemble" in assemble["run"]
    assert "updater-manifest" in _job("promote-images")["needs"]
    assert "updater-manifest" in _job("publish")["needs"]

    publish_steps = [step.get("name") for step in _job("publish")["steps"]]
    assert publish_steps.index("Verify the live updater manifest") > publish_steps.index("Flip draft → published")
    verify = _job_step("publish", "Verify the live updater manifest")["run"]
    assert "scripts/updater_manifest.py verify" in verify
    assert "--draft=true" in verify
    assert verify.rstrip().endswith("exit 1")
