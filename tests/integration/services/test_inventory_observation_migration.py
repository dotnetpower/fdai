"""Core normalized inventory observation migration contract tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260905_core_inventory_observation_journal.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("core_inventory_observation_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_observation_migration_is_linear_and_core_owned() -> None:
    module = _load()

    assert module.down_revision == "core_operational_state_transitions_20260902"
    assert module.migration_owner == "core-control-plane"
    assert module.owned_tables == (
        "inventory_observation_journal",
        "inventory_observation_pending_tombstone",
    )


def test_inventory_observation_upgrade_creates_append_only_shadow_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.upgrade()

    sql = "\n".join(statements)
    assert "CREATE TABLE inventory_observation_journal" in sql
    assert "CREATE TABLE inventory_observation_pending_tombstone" in sql
    assert "operation_status TEXT" in sql
    assert "projection_mode TEXT NOT NULL DEFAULT 'shadow'" in sql
    assert "inventory observation journal is append-only" in sql


def test_inventory_observation_rollback_requires_stopped_writers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)

    module.downgrade()

    assert module.rollback == {
        "strategy": "drop-rebuildable-inventory-observation-journal",
        "restores": "core_operational_state_transitions_20260902",
        "requires": "inventory-observation-writers-stopped",
    }
    sql = "\n".join(statements)
    assert sql.index("DROP TABLE inventory_observation_pending_tombstone") < sql.index(
        "DROP TABLE inventory_observation_journal"
    )
