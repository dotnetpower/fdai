from __future__ import annotations

import runpy
from pathlib import Path

REVISION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations/branches/core-control-plane/versions"
    / "20260912_core_recent_resource_changes.py"
)


def test_recent_resource_change_indexes_match_query_and_fence() -> None:
    source = REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(REVISION))

    assert migration["down_revision"] == "core_post_release_closure_20260912"
    assert migration["migration_owner"] == "core-control-plane"
    assert "inventory_observation_recent_object_change_idx" in source
    assert "inventory_arg_change_event_fence_idx" in source
    assert "source_identity='fdai.delivery.azure.arg_resource_changes'" in source
