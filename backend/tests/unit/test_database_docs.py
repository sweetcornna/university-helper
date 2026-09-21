"""Guardrails for the active database bootstrap documentation."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATABASE_README = REPO_ROOT / "database" / "README.md"
REQUIRED_DATABASE_FILES = (
    REPO_ROOT / "database" / "00-schema.sql",
    REPO_ROOT / "database" / "01-create_tenant.sql",
    REPO_ROOT / "database" / "02-bootstrap-tenant-template.sh",
    REPO_ROOT / "database" / "templates" / "tenant_template.sql",
)
REQUIRED_REPO_PATHS = (
    "database/00-schema.sql",
    "database/01-create_tenant.sql",
    "database/02-bootstrap-tenant-template.sh",
    "database/templates/tenant_template.sql",
)


def test_database_readme_uses_current_bootstrap_files():
    document = DATABASE_README.read_text(encoding="utf-8")

    for path, repo_path in zip(REQUIRED_DATABASE_FILES, REQUIRED_REPO_PATHS, strict=True):
        assert path.is_file(), f"missing documented database file: {repo_path}"
        assert repo_path in document, f"README must name {repo_path}"


def test_database_readme_has_no_stale_paths_or_transactional_tenant_call():
    document = DATABASE_README.read_text(encoding="utf-8")

    assert "E:/project/sign_in/unified-signin-platform" not in document
    assert not re.search(r"(?m)^\s*(?:chmod\s+\+x\s+)?(?:\./)?init\.sh\b", document)
    for stale_command in ("-f schema.sql", "-f create_tenant.sql", "-f tenant_template.sql"):
        assert stale_command not in document
    assert not re.search(r"\bSELECT\s+create_tenant_database\s*\(", document, re.IGNORECASE)


def test_database_readme_separates_entrypoint_and_root_manual_workflows():
    document = DATABASE_README.read_text(encoding="utf-8")
    docker_start = document.index("### Docker entrypoint")
    manual_start = document.index("### 宿主机手工初始化", docker_start)
    tenant_start = document.index("## 创建新租户", manual_start)
    docker_block = document[docker_start:manual_start]
    manual_block = document[manual_start:tenant_start]
    tenant_block = document[tenant_start:]

    assert "docker-entrypoint-initdb" in docker_block
    assert [docker_block.index(path) for path in REQUIRED_REPO_PATHS] == sorted(
        docker_block.index(path) for path in REQUIRED_REPO_PATHS
    )
    assert "cd /path/to/university-helper" in manual_block
    assert "-f database/00-schema.sql" in manual_block
    assert "-f database/01-create_tenant.sql" in manual_block
    assert "-f database/templates/tenant_template.sql" in manual_block
    assert "createdb -U postgres --template=tenant_template tenant_alice" in tenant_block
    assert "AuthService" in tenant_block
    assert "autocommit=True" in tenant_block
