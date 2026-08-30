"""Regression tests for tenant migration result accounting."""

import importlib.util
import logging
from pathlib import Path

SCRIPT_SOURCE = Path(__file__).resolve().parents[1] / "migrate_tenants.py"
_SPEC = importlib.util.spec_from_file_location(
    "migrate_tenants_test_module", SCRIPT_SOURCE
)
assert _SPEC is not None and _SPEC.loader is not None
migrate_tenants = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migrate_tenants)


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
