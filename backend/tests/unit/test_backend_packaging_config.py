import fnmatch
import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = BACKEND_ROOT / "pyproject.toml"


def _project_config() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _assert_local_metadata_file(value: object) -> None:
    if not isinstance(value, dict) or "file" not in value:
        return

    target = (BACKEND_ROOT / value["file"]).resolve()
    assert target.is_relative_to(BACKEND_ROOT.resolve())
    assert target.is_file()


def test_project_metadata_does_not_reference_parent_files():
    project = _project_config()["project"]
    readme = project["readme"]

    if isinstance(readme, str):
        _assert_local_metadata_file({"file": readme})
    else:
        _assert_local_metadata_file(readme)
    _assert_local_metadata_file(project["license"])


def test_setuptools_discovery_includes_every_app_package():
    config = _project_config()
    discovery = config["tool"]["setuptools"]["packages"]["find"]

    assert discovery["where"] == ["."]
    assert discovery["namespaces"] is False

    include_patterns = discovery["include"]
    app_packages = {
        init_file.parent.relative_to(BACKEND_ROOT).as_posix().replace("/", ".")
        for init_file in (BACKEND_ROOT / "app").rglob("__init__.py")
    }
    assert {
        "app",
        "app.api.v1",
        "app.core",
        "app.services.course.chaoxing",
        "app.services.course.zhihuishu",
    } <= app_packages
    assert all(any(fnmatch.fnmatchcase(package, pattern) for pattern in include_patterns) for package in app_packages)
