from __future__ import annotations

import runpy
from pathlib import Path

REVISION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations/branches/core-control-plane/versions"
    / "20260912_core_retire_resource_change_receipts.py"
)


def test_resource_change_receipt_retirement_is_reversible() -> None:
    source = REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(REVISION))

    assert migration["down_revision"] == "core_resource_change_receipts_20260912"
    assert migration["migration_owner"] == "core-control-plane"
    assert migration["owned_tables"] == ("inventory_change_event_receipt",)
    assert "DROP TABLE inventory_change_event_receipt" in source
    assert "CREATE TABLE inventory_change_event_receipt" in source
