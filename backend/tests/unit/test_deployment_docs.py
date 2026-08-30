"""Guardrails for production deployment documentation."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "DEPLOYMENT.md"
ROOT_ENV_EXAMPLE = REPO_ROOT / ".env.example"
CHINESE_ENV_HEADER = "## 环境变量（生产）"
CHINESE_ENV_NEXT_HEADER = "## 推送热修（小改动）"
FERNET_COMMAND = re.compile(
    r'python -c "from cryptography\.fernet import Fernet; print\(Fernet\.generate_key\(\)\.decode\(\)\)"'
)
BACKUP_SECTIONS = (
    ("English operations", "## Operations", "## Staging on the same host"),
    ("中文运维", "## 运维", "## 故障排查"),
)


def _chinese_production_environment_block(document: str) -> str:
    start = document.index(CHINESE_ENV_HEADER)
    end = document.index(CHINESE_ENV_NEXT_HEADER, start)
    return document[start:end]


def test_chinese_production_env_documents_credential_encryption_key():
    deployment = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    env_example = ROOT_ENV_EXAMPLE.read_text(encoding="utf-8")
    chinese_block = _chinese_production_environment_block(deployment)

    generated_key_command = FERNET_COMMAND.search(env_example)
    assert generated_key_command, ".env.example must document Fernet key generation"
    assert "CREDENTIAL_ENCRYPTION_KEY=" in chinese_block
    assert generated_key_command.group(0) in chinese_block
    assert "禁止入仓" in chinese_block


def test_active_operations_backup_sections_use_the_atomic_encrypted_helper():
    deployment = DEPLOYMENT_DOC.read_text(encoding="utf-8")

    for label, start_marker, end_marker in BACKUP_SECTIONS:
        start = deployment.index(start_marker)
        end = deployment.index(end_marker, start)
        section = deployment[start:end]

        assert re.search(
            r"(?:bash\s+)?(?:\./)?scripts/db_backup\.sh\b", section
        ), f"{label} must invoke the repository backup helper"
        assert re.search(r"AGE_RECIPIENT(?:_FILE)?=", section), f"{label} must configure an age recipient"
        if label == "中文运维":
            assert re.search(
                r"bash\s+scripts/db_backup\.sh\s+/opt/backups/university-helper",
                section,
            )
        assert not re.search(
            r"\bpg_dump(?:all)?\b[\s\S]*\s>", section, re.IGNORECASE
        ), f"{label} must not redirect pg_dump into a final backup path"
