"""Keep release documentation aligned with the image promotion workflow."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RELEASING_DOC = REPO_ROOT / "docs" / "RELEASING.md"


def _workflow() -> dict:
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))


def _job_needs(workflow: dict, job_name: str) -> set[str]:
    raw_needs = workflow["jobs"][job_name].get("needs", [])
    if isinstance(raw_needs, str):
        return {raw_needs}
    return set(raw_needs)


def _documented_job_needs(document: str, job_name: str) -> set[str]:
    marker = f"The `{job_name}` job waits for "
    match = re.search(rf"{re.escape(marker)}(?P<dependencies>[^.]+)\.", document, flags=re.DOTALL)
    assert match is not None, f"{RELEASING_DOC} must document the {job_name} dependency gate"
    return set(re.findall(r"`([^`]+)`", match.group("dependencies")))


def _named_step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_releasing_documents_current_promotion_gates_and_failure_semantics():
    workflow = _workflow()
    document = RELEASING_DOC.read_text(encoding="utf-8")
    jobs = workflow["jobs"]

    for job_name in ("promote-images", "publish"):
        assert _documented_job_needs(document, job_name) == _job_needs(workflow, job_name)

    for job_name in ("app-image", "web-image"):
        job = jobs[job_name]
        build_step = _named_step(job, f"Build & push {job_name.removesuffix('-image')} image")
        tags = build_step["with"]["tags"]

        assert job["outputs"]["digest"] == "${{ steps.build.outputs.digest }}"
        assert "image_version" in tags
        assert ":latest" not in tags

    promotion_job = jobs["promote-images"]
    promotion_step = _named_step(promotion_job, "Promote immutable image digests to latest")
    promotion_script = promotion_step["run"]

    assert promotion_script.count("docker buildx imagetools create") == 2
    assert "${APP_IMAGE}@${APP_DIGEST}" in promotion_script
    assert "${WEB_IMAGE}@${WEB_DIGEST}" in promotion_script
    assert promotion_job.get("if") != "always()"
    assert jobs["publish"].get("if") != "always()"

    assert "immutable-first" in document.lower()
    assert "all-gates-before-promotion" in document
    assert "@<digest>" in document
    assert "not atomic" in document
    assert "draft/unpublished" in document
