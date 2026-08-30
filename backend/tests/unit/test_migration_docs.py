"""Guardrails for the active documentation's split Alembic heads."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_MIGRATION_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "DEVELOPMENT.md",
    REPO_ROOT / "docs" / "DEPLOYMENT.md",
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "site" / "wiki.html",
)
UNQUALIFIED_HEAD = re.compile(r"\balembic\s+upgrade\s+head\b")
MAIN_DB_COMMAND = "alembic upgrade main_db@head"
TENANT_MIGRATION_COMMAND = "python scripts/migrate_tenants.py"


def test_active_docs_use_explicit_migration_branches():
    contents = {path: path.read_text(encoding="utf-8") for path in ACTIVE_MIGRATION_DOCS}

    for path, text in contents.items():
        relative_path = path.relative_to(REPO_ROOT)
        assert not UNQUALIFIED_HEAD.search(text), f"{relative_path} must not suggest an unqualified Alembic head"
        assert MAIN_DB_COMMAND in text, f"{relative_path} must name the main_db head"
        assert TENANT_MIGRATION_COMMAND in text, f"{relative_path} must name the tenant helper"
