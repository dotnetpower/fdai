"""Core operational history lifecycle migration contract tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260906_core_operational_history_lifecycle.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "operational_history_lifecycle_migration",
        MIGRATION,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operational_history_lifecycle_migration_is_linear_and_core_owned() -> None:
    module = _load()

    assert module.down_revision == "core_inventory_observation_journal_20260905"
    assert module.migration_owner == "core-control-plane"
    assert "inventory_resource_incarnation" in module.owned_tables
    assert "inventory_observation_partition_pin_event" in module.owned_tables
    assert "operational_history_certification_receipt" in module.owned_tables


def test_upgrade_creates_append_only_evidence_and_mutable_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.upgrade()

    sql = "\n".join(statements)
    assert "CREATE TABLE inventory_resource_incarnation" in sql
    assert "CREATE TABLE inventory_observation_partition" in sql
    assert "CREATE TABLE inventory_observation_checkpoint" in sql
    assert "CREATE TABLE operational_archive_artifact" in sql
    assert "operational history lifecycle evidence is append-only" in sql
    assert "GRANT UPDATE ON TABLE" in sql


def test_downgrade_drops_dependents_before_policy_and_requires_stopped_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.downgrade()

    assert module.rollback["requires"] == ("observation-archive-and-certification-writers-stopped")
    sql = "\n".join(statements)
    assert sql.index("DROP TABLE inventory_observation_lifecycle_binding") < sql.index(
        "DROP TABLE inventory_resource_incarnation"
    )
    assert sql.index("DROP TABLE inventory_observation_partition") < sql.index(
        "DROP TABLE operational_retention_policy"
    )
