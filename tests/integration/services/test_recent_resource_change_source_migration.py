from __future__ import annotations

import runpy
from pathlib import Path

REVISION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations/branches/core-control-plane/versions"
    / "20260912_core_resource_change_sources.py"
)


def test_resource_change_source_index_uses_reviewed_adapters() -> None:
    source = REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(REVISION))

    assert migration["down_revision"] == "core_retire_resource_change_receipts_20260912"
    assert migration["migration_owner"] == "core-control-plane"
    assert "source_identity='fdai.delivery.azure.arg_resource_changes'" in source
    assert "source_identity='azure_event_grid.resource_change'" in source
