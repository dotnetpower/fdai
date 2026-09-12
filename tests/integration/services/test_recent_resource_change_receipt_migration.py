from __future__ import annotations

import runpy
from pathlib import Path

REVISION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations/branches/core-control-plane/versions"
    / "20260912_core_resource_change_receipts.py"
)


def test_resource_change_receipt_migration_is_owned_and_bounded() -> None:
    source = REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(REVISION))

    assert migration["down_revision"] == "core_recent_resource_changes_20260912"
    assert migration["migration_owner"] == "core-control-plane"
    assert migration["owned_tables"] == ("inventory_change_event_receipt",)
    assert "source_event_id TEXT PRIMARY KEY" in source
    assert "'snapshot_covered'" in source
    assert "GRANT SELECT, INSERT" in source
