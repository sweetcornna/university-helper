"""Guard the local Ruff hook against drifting from the development pin."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
DEV_REQUIREMENTS = REPO_ROOT / "backend" / "requirements-dev.txt"
RUFF_PIN_RE = re.compile(r"^ruff==(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$", re.IGNORECASE)


def _ruff_dev_version() -> str:
    pins = []
    for line in DEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        match = RUFF_PIN_RE.fullmatch(candidate)
        if match:
            pins.append(match.group("version"))
    assert len(pins) == 1, "requirements-dev.txt must pin Ruff exactly once"
    return pins[0]


def test_precommit_ruff_hooks_match_the_development_pin() -> None:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    ruff_repo = next(repo for repo in config["repos"] if repo["repo"] == "https://github.com/astral-sh/ruff-pre-commit")
    hooks = {hook["id"]: hook for hook in ruff_repo["hooks"]}

    assert ruff_repo["rev"] == f"v{_ruff_dev_version()}"
    assert {"ruff", "ruff-format"}.issubset(hooks)
