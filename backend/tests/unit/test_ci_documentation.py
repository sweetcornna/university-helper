"""Guardrails for documentation claims about the active CI checks."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
ACTIVE_DOCS = (
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.zh-CN.md",
    REPO_ROOT / "docs" / "DEVELOPMENT.md",
)
CI_TERMS = re.compile(r"\b(?:CI|gate|gating|blocking|required|green|must)\b", re.IGNORECASE)
NEGATION_OR_REPORTING = re.compile(r"\b(?:not|no|non-blocking|report-only)\b|exit-code\s*:\s*`?0`?", re.IGNORECASE)
MYPY_TOKEN = re.compile(r"\bmypy\b", re.IGNORECASE)


def _doc_text() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in ACTIVE_DOCS}


def _workflow() -> dict:
    parsed = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_active_workflow_exposes_only_the_actual_backend_checks():
    workflow = _workflow()
    backend = workflow["jobs"]["backend"]

    assert backend["name"] == "Backend (Ruff · Bandit · pytest)"
    run_scripts = [str(step["run"]) for step in backend["steps"] if "run" in step]
    assert run_scripts
    assert not any(MYPY_TOKEN.search(script) for script in run_scripts)


def test_active_workflow_marks_report_only_security_checks_precisely():
    workflow = _workflow()

    trivy_steps = [
        step for step in workflow["jobs"]["docker-build"]["steps"] if step.get("name") == "Trivy vulnerability scan"
    ]
    assert len(trivy_steps) == 1
    assert str(trivy_steps[0]["with"]["exit-code"]) == "0"

    audit_steps = [
        step
        for step in workflow["jobs"]["frontend"]["steps"]
        if step.get("name") == "npm audit (high+critical only, non-blocking)"
    ]
    assert len(audit_steps) == 1
    assert audit_steps[0]["run"] == "npm audit --omit=dev --audit-level=high || true"


def test_active_docs_do_not_call_non_gates_required_checks():
    docs = _doc_text()

    for path, text in docs.items():
        for line in text.splitlines():
            lower_line = line.lower()
            if ("mypy" in lower_line or "trivy" in lower_line) and CI_TERMS.search(line):
                assert NEGATION_OR_REPORTING.search(
                    line
                ), f"{path.relative_to(REPO_ROOT)} misstates mypy/Trivy CI semantics: {line}"

    contributing = docs[REPO_ROOT / "CONTRIBUTING.md"]
    readme = docs[REPO_ROOT / "README.md"]
    assert re.search(r"mypy.*not currently run by CI", contributing, re.IGNORECASE | re.DOTALL)
    assert re.search(r"Trivy.*report-only.*exit-code:\s*0", contributing, re.IGNORECASE | re.DOTALL)
    assert re.search(r"Trivy.*report-only", readme, re.IGNORECASE | re.DOTALL)
