"""Keep release documentation aligned with desktop workflow runners."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
RELEASING_DOC = REPO_ROOT / "docs" / "RELEASING.md"
RUNNER_LIST_START = "The desktop matrix currently uses these runner labels:"
RUNNER_LIST_END = "macOS caveat:"


def _desktop_runner_labels() -> set[str]:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    entries = workflow["jobs"]["desktop"]["strategy"]["matrix"]["include"]
    return {entry["os"] for entry in entries}


def test_releasing_documents_current_desktop_runner_matrix():
    document = RELEASING_DOC.read_text(encoding="utf-8")
    start = document.index(RUNNER_LIST_START) + len(RUNNER_LIST_START)
    end = document.index(RUNNER_LIST_END, start)
    runner_section = document[start:end]
    documented = set(re.findall(r"(?m)^- [^:]+: `([^`]+)`$", runner_section))

    assert documented == _desktop_runner_labels()
