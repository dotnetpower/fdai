"""Contract tests for persisted inventory activity counts."""

from __future__ import annotations

import runpy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION_PATH = (
    _REPO_ROOT / "service-migrations/branches/core-control-plane/versions/"
    "20260917_core_inventory_activity_counts.py"
)
_WRITER_PATH = (
    _REPO_ROOT / "services/core-control-plane/src/fdai/delivery/persistence/"
    "postgres_inventory_snapshot.py"
)


class _CaptureOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def test_inventory_activity_count_migration_is_additive_and_reversible() -> None:
    migration = runpy.run_path(str(_MIGRATION_PATH))
    assert migration["revision"] == "core_inventory_activity_counts_20260917"
    assert migration["down_revision"] == "core_inventory_temporal_axes_20260916"
    assert migration["migration_owner"] == "core-control-plane"
    assert migration["owned_tables"] == ("inventory_snapshot",)

    upgrade = _CaptureOp()
    migration["upgrade"].__globals__["op"] = upgrade
    migration["upgrade"]()
    upgrade_sql = "\n".join(upgrade.statements)
    assert "ADD COLUMN resource_count BIGINT" in upgrade_sql
    assert "ADD COLUMN link_count BIGINT" in upgrade_sql
    assert "FROM inventory_snapshot_resource" in upgrade_sql
    assert "FROM inventory_snapshot_link" in upgrade_sql
    assert "snapshot.status IN ('active', 'superseded')" in upgrade_sql

    downgrade = _CaptureOp()
    migration["downgrade"].__globals__["op"] = downgrade
    migration["downgrade"]()
    downgrade_sql = "\n".join(downgrade.statements)
    assert "DROP COLUMN link_count" in downgrade_sql
    assert "DROP COLUMN resource_count" in downgrade_sql


def test_inventory_promotion_records_counts_in_the_pointer_transaction() -> None:
    source = _WRITER_PATH.read_text(encoding="utf-8")
    assert "resource_count=(SELECT COUNT(*) FROM inventory_snapshot_resource " in source
    assert "link_count=(SELECT COUNT(*) FROM inventory_snapshot_link " in source
