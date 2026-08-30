"""Keep Dependabot coverage aligned with the repository's dependency manifests."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPENDABOT_CONFIG = REPO_ROOT / ".github" / "dependabot.yml"
IGNORED_PATH_PARTS = {".claude", ".git", ".venv", "node_modules"}
MANIFEST_ECOSYSTEMS = {
    "Cargo.lock": "cargo",
    "Cargo.toml": "cargo",
    "package-lock.json": "npm",
    "package.json": "npm",
    "pyproject.toml": "pip",
    "requirements-dev.txt": "pip",
    "requirements.txt": "pip",
}


def _dependency_directories() -> set[tuple[str, str]]:
    directories: set[tuple[str, str]] = set()
    for filename, ecosystem in MANIFEST_ECOSYSTEMS.items():
        for manifest in REPO_ROOT.rglob(filename):
            if any(part in IGNORED_PATH_PARTS for part in manifest.parts):
                continue
            relative_directory = manifest.parent.relative_to(REPO_ROOT).as_posix()
            directory = "/" if relative_directory == "." else f"/{relative_directory}"
            directories.add((ecosystem, directory))
    return directories


def _dependabot_updates() -> list[dict[str, object]]:
    config = yaml.safe_load(DEPENDABOT_CONFIG.read_text())
    assert isinstance(config, dict)
    assert config.get("version") == 2
    updates = config.get("updates")
    assert isinstance(updates, list)
    assert all(isinstance(update, dict) for update in updates)
    return updates


def test_dependabot_yaml_covers_each_dependency_directory_once():
    updates = _dependabot_updates()
    configured = [(update.get("package-ecosystem"), update.get("directory")) for update in updates]

    assert len(configured) == len(set(configured)), "duplicate ecosystem/directory entry"

    expected = _dependency_directories()
    assert expected
    assert expected <= set(configured)

    for ecosystem, directory in expected:
        update = next(
            update
            for update in updates
            if update.get("package-ecosystem") == ecosystem and update.get("directory") == directory
        )
        assert update["schedule"] == {"interval": "weekly", "day": "monday"}
        assert update["open-pull-requests-limit"] == 5
        assert update["labels"]
