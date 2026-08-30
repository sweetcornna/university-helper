"""Regression tests for tenant migration result accounting."""

import importlib.util
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_SOURCE = Path(__file__).resolve().parents[1] / "migrate_tenants.py"
_SPEC = importlib.util.spec_from_file_location(
    "migrate_tenants_test_module", SCRIPT_SOURCE
)
assert _SPEC is not None and _SPEC.loader is not None
migrate_tenants = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migrate_tenants)


def _load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_database_environment(monkeypatch):
    monkeypatch.setenv("MAIN_DB_USER", "user")
    monkeypatch.setenv("MAIN_DB_PASSWORD", "password")
    monkeypatch.setenv("MAIN_DB_HOST", "db.example.test")
    monkeypatch.setenv("MAIN_DB_PORT", "5432")


def _successful_alembic_stub(calls):
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


@pytest.mark.parametrize(
    ("dry_run", "expected_command"),
    [
        (False, ["alembic", "upgrade", "tenant_db@head"]),
        (True, ["alembic", "current"]),
    ],
)
def test_migration_uses_repo_backend_from_any_cwd(
    monkeypatch, tmp_path, dry_run, expected_command
):
    caller_cwd = tmp_path / "unrelated-cwd"
    caller_cwd.mkdir()
    monkeypatch.chdir(caller_cwd)
    _set_database_environment(monkeypatch)
    calls = []
    monkeypatch.setattr(
        migrate_tenants.subprocess, "run", _successful_alembic_stub(calls)
    )

    assert migrate_tenants._migrate_one("tenant_alice", dry_run) is True

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == expected_command
    assert kwargs["cwd"] == SCRIPT_SOURCE.parents[1] / "backend"
    assert kwargs["env"]["ALEMBIC_DB_URL"].endswith("/tenant_alice")


def test_migration_uses_container_backend_layout_from_any_cwd(monkeypatch, tmp_path):
    container_root = tmp_path / "srv" / "backend"
    container_script = container_root / "scripts" / "migrate_tenants.py"
    container_script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT_SOURCE, container_script)
    (container_root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    module = _load_script(container_script, "migrate_tenants_container_layout")

    caller_cwd = tmp_path / "different-cwd"
    caller_cwd.mkdir()
    monkeypatch.chdir(caller_cwd)
    _set_database_environment(monkeypatch)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", _successful_alembic_stub(calls))

    assert module._migrate_one("tenant_alice", False) is True

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == ["alembic", "upgrade", "tenant_db@head"]
    assert kwargs["cwd"] == container_root


def test_migration_fails_clearly_without_alembic_config(monkeypatch, tmp_path, caplog):
    missing_root = tmp_path / "missing-config"
    missing_script = missing_root / "scripts" / "migrate_tenants.py"
    missing_script.parent.mkdir(parents=True)
    shutil.copy2(SCRIPT_SOURCE, missing_script)
    module = _load_script(missing_script, "migrate_tenants_missing_config")

    _set_database_environment(monkeypatch)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", _successful_alembic_stub(calls))
    caplog.set_level(logging.ERROR, logger="migrate_tenants")

    assert module._migrate_one("tenant_alice", False) is False
    assert calls == []
    assert "Alembic config not found" in caplog.text


def _run_stubbed_migration(monkeypatch, targets, existing, successful):
    db_checks = []
    migration_calls = []

    def fake_db_exists(name):
        db_checks.append(name)
        return name in existing

    def fake_migrate_one(name, dry_run):
        migration_calls.append((name, dry_run))
        return name in successful

    monkeypatch.setattr(migrate_tenants, "_db_exists", fake_db_exists)
    monkeypatch.setattr(migrate_tenants, "_migrate_one", fake_migrate_one)
    result = migrate_tenants.main(["--only", ",".join(targets)])
    return result, db_checks, migration_calls


def test_migration_summary_separates_success_skip_and_failure(monkeypatch, caplog):
    targets = ["tenant_ok", "tenant_missing", "tenant_failed"]
    caplog.set_level(logging.INFO, logger="migrate_tenants")

    result, db_checks, migration_calls = _run_stubbed_migration(
        monkeypatch,
        targets,
        existing={"tenant_ok", "tenant_failed"},
        successful={"tenant_ok"},
    )

    assert result == 1
    assert db_checks == targets
    assert migration_calls == [("tenant_ok", False), ("tenant_failed", False)]
    assert "FAILED tenants (1): tenant_failed" in caplog.text
    assert "migration summary: migrated=1 skipped=1 failed=1" in caplog.text


def test_only_missing_databases_are_skipped(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="migrate_tenants")

    result, db_checks, migration_calls = _run_stubbed_migration(
        monkeypatch,
        ["tenant_missinga", "tenant_missingb"],
        existing=set(),
        successful=set(),
    )

    assert result == 0
    assert db_checks == ["tenant_missinga", "tenant_missingb"]
    assert migration_calls == []
    assert "ok: 0 tenant(s) migrated" in caplog.text
    assert "migration summary: migrated=0 skipped=2 failed=0" in caplog.text


def test_all_existing_databases_migrate_successfully(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="migrate_tenants")

    result, db_checks, migration_calls = _run_stubbed_migration(
        monkeypatch,
        ["tenant_a", "tenant_b"],
        existing={"tenant_a", "tenant_b"},
        successful={"tenant_a", "tenant_b"},
    )

    assert result == 0
    assert db_checks == ["tenant_a", "tenant_b"]
    assert migration_calls == [("tenant_a", False), ("tenant_b", False)]
    assert "ok: 2 tenant(s) migrated" in caplog.text
    assert "migration summary: migrated=2 skipped=0 failed=0" in caplog.text
