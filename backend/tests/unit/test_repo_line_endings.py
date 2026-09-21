"""Scripts that run inside Linux containers must stay LF on every checkout."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GITATTRIBUTES = REPO_ROOT / ".gitattributes"
BOOTSTRAP_SCRIPT = REPO_ROOT / "database" / "02-bootstrap-tenant-template.sh"


def _rules() -> dict[str, str]:
    rules: dict[str, str] = {}
    for raw in GITATTRIBUTES.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern, _, attrs = line.partition(" ")
        rules[pattern] = " ".join(attrs.split())
    return rules


def test_container_scripts_are_forced_to_lf():
    rules = _rules()
    for pattern in ("*.sh", "*.sql", "database/**", "*.nsh", "docker-compose*.yml"):
        assert rules.get(pattern) == "text eol=lf", pattern


def test_gitattributes_does_not_renormalize_every_file():
    assert "*" not in _rules()


def test_database_init_files_have_no_carriage_returns():
    for path in sorted((REPO_ROOT / "database").rglob("*")):
        if path.is_file() and path.suffix in {".sh", ".sql"}:
            assert b"\r" not in path.read_bytes(), path


def test_bootstrap_marks_template_without_blocking_backups():
    script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert "ALTER DATABASE tenant_template WITH IS_TEMPLATE true" in script
    commands = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not any("ALLOW_CONNECTIONS" in line for line in commands)
