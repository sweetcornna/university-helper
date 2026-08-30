"""Keep desktop updater documentation aligned with the release workflow."""

import re
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
