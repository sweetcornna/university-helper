"""Guardrails for facts presented in the active defense document."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFENSE_DOC = REPO_ROOT / "docs" / "答辩稿.md"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
DEPLOYMENT_SCRIPTS = REPO_ROOT / "scripts"
BACKEND_TESTS = REPO_ROOT / "backend" / "tests"
E2E_TESTS_DIR = BACKEND_TESTS / "e2e"
LANGUAGE_BY_SUFFIX = {".ps1": "PowerShell", ".py": "Python", ".sh": "Bash"}


def _document() -> str:
    return DEFENSE_DOC.read_text(encoding="utf-8")


def _active_deployment_scripts() -> list[Path]:
    return sorted(path for path in DEPLOYMENT_SCRIPTS.glob("deploy_server.*") if path.is_file())


def _pytest_test_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file()
        and path.suffix == ".py"
        and path.name != "__init__.py"
        and (path.name.startswith("test_") or path.name.endswith("_test.py"))
    )


def test_backend_runtime_version_matches_python_version_file():
    version = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    backend_line = next(line for line in _document().splitlines() if "语言与框架" in line)

    assert f"Python {version}" in backend_line


def test_frontend_state_claim_matches_package_and_source():
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    dependencies = {
        name.lower() for section in ("dependencies", "devDependencies") for name in package.get(section, {})
    }
    state_line = next(line for line in _document().splitlines() if "状态管理" in line)
    frontend_sources = (
        path
        for pattern in ("*.js", "*.jsx", "*.ts", "*.tsx")
        for path in (REPO_ROOT / "frontend" / "src").rglob(pattern)
    )
    uses_react_context = any("createContext" in path.read_text(encoding="utf-8") for path in frontend_sources)

    if "zustand" in dependencies:
        assert "Zustand" in state_line
    else:
        assert "Zustand" not in state_line
        assert uses_react_context
        assert "React Hooks" in state_line
        assert "Context" in state_line


def test_deployment_script_claim_matches_active_script_extensions():
    scripts = _active_deployment_scripts()
    assert scripts, "the active deployment script set must not be empty"
    assert all(path.parent == DEPLOYMENT_SCRIPTS for path in scripts)

    suffixes = {path.suffix.lower() for path in scripts}
    assert suffixes <= LANGUAGE_BY_SUFFIX.keys()
    expected_languages = {LANGUAGE_BY_SUFFIX[suffix] for suffix in suffixes}
    deployment_line = next(line for line in _document().splitlines() if "部署脚本" in line)

    for language in expected_languages:
        assert language in deployment_line
    for suffix, language in LANGUAGE_BY_SUFFIX.items():
        assert (language in deployment_line) == (suffix in suffixes)


def test_backend_test_claim_lists_actual_categories_and_tracks_e2e_directory():
    backend_line = next(line for line in _document().splitlines() if line.startswith("- **后端测试：**"))

    for category in ("单元测试", "集成测试", "性能测试", "契约测试", "静态守护测试"):
        assert category in backend_line

    if _pytest_test_files(E2E_TESTS_DIR):
        assert "端到端测试" in backend_line
    else:
        assert "端到端测试" not in backend_line
