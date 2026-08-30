import ast
from pathlib import Path

from api.answer import AI as LegacyAI
from api.answer import SiliconFlow as LegacySiliconFlow
from app.services.course.chaoxing.answer_providers import AI, SiliconFlow

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ANSWER_BASE = BACKEND_ROOT / "app/services/course/chaoxing/answer_base.py"
LEGACY_ANSWER = BACKEND_ROOT / "api/answer.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(node: ast.AST) -> set[tuple[int, str | None]]:
    return {(child.level, child.module) for child in ast.walk(node) if isinstance(child, ast.ImportFrom)}


def test_answer_base_imports_providers_without_legacy_reverse_dependency():
    answer_base = _parse(ANSWER_BASE)
    assert (0, "api.answer") not in _imports(answer_base)

    tiku = next(node for node in answer_base.body if isinstance(node, ast.ClassDef) and node.name == "Tiku")
    query = next(node for node in tiku.body if isinstance(node, ast.FunctionDef) and node.name == "query")
    assert (1, "answer_providers") in _imports(query)

    legacy_answer = _parse(LEGACY_ANSWER)
    assert (0, "app.services.course.chaoxing.answer") in _imports(legacy_answer)


def test_legacy_answer_shim_reexports_canonical_providers():
    assert LegacyAI is AI
    assert LegacySiliconFlow is SiliconFlow
