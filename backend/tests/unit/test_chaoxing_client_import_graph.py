import ast
import pickle
from pathlib import Path

from app.services.course.chaoxing.client import StudyResult
from app.services.course.chaoxing.constants import StudyResult as ConstantStudyResult

SERVICE_ROOT = Path(__file__).resolve().parents[2] / "app/services/course/chaoxing"
TARGET_MODULES = {"client", "constants", "video_service", "work_legacy_service"}
PACKAGE_PREFIX = "app.services.course.chaoxing."


def _local_imports(module: str) -> set[str]:
    tree = ast.parse((SERVICE_ROOT / f"{module}.py").read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 1:
                imports.add(node.module.split(".", 1)[0])
            elif node.level == 0 and node.module.startswith(PACKAGE_PREFIX):
                imports.add(node.module.removeprefix(PACKAGE_PREFIX).split(".", 1)[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PACKAGE_PREFIX):
                    imports.add(alias.name.removeprefix(PACKAGE_PREFIX).split(".", 1)[0])
    return imports


def _is_cyclic(start: str, graph: dict[str, set[str]]) -> bool:
    pending = list(graph[start])
    visited = set()
    while pending:
        module = pending.pop()
        if module == start:
            return True
        if module not in visited:
            visited.add(module)
            pending.extend(graph[module])
    return False


def test_client_still_reexports_the_canonical_study_result():
    assert StudyResult is ConstantStudyResult
    assert StudyResult.__module__ == "app.services.course.chaoxing.client"
    assert [(member.name, member.value) for member in StudyResult] == [
        ("SUCCESS", 0),
        ("FORBIDDEN", 1),
        ("ERROR", 2),
        ("TIMEOUT", 3),
        ("CANCELLED", 4),
    ]
    assert {member for member in StudyResult if member.is_success()} == {StudyResult.SUCCESS}
    assert {member for member in StudyResult if member.is_failure()} == {
        StudyResult.FORBIDDEN,
        StudyResult.ERROR,
        StudyResult.TIMEOUT,
    }
    assert {member for member in StudyResult if member.is_cancelled()} == {StudyResult.CANCELLED}
    assert pickle.loads(pickle.dumps(StudyResult.TIMEOUT)) is StudyResult.TIMEOUT


def test_client_video_and_work_import_graph_is_acyclic():
    all_imports = {module: _local_imports(module) for module in TARGET_MODULES}
    graph = {module: imports & TARGET_MODULES for module, imports in all_imports.items()}

    assert "client" not in all_imports["video_service"]
    assert "client" not in all_imports["work_legacy_service"]
    assert graph["constants"] == set()
    assert all(not _is_cyclic(module, graph) for module in graph)
