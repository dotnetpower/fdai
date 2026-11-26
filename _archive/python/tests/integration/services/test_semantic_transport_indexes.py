"""Contracts for Core-owned Operator semantic transport indexes."""

from __future__ import annotations

import runpy
from pathlib import Path

_REVISION = (
    Path(__file__).resolve().parents[3]
    / "service-migrations"
    / "branches"
    / "core-control-plane"
    / "versions"
    / "20260908_core_semantic_transport_indexes.py"
)
_ORDERING_REVISION = _REVISION.parent / "20260908_core_semantic_transport_ordering_indexes.py"


def test_semantic_transport_indexes_follow_core_head_and_query_shapes() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_REVISION))

    assert migration["down_revision"] == "core_oi16_synthetic_retention_20260907"
    assert migration["migration_owner"] == "core-control-plane"
    assert migration["owned_tables"] == ("state_kv",)
    assert "state_kv_operator_semantic_claim_idx" in source
    assert "value ->> 'outbox_namespace'" in source
    assert "value ->> 'accepted_at'" in source
    assert "state_kv_operator_semantic_replay_idx" in source
    assert "value ->> 'principal_id'" in source
    assert "value ->> 'request_id'" in source
    assert "value ->> 'event_sequence'" in source
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" not in source
    assert source.count("CREATE INDEX CONCURRENTLY ") == 2
    for name in (
        "state_kv_operator_semantic_claim_idx",
        "state_kv_operator_semantic_replay_idx",
    ):
        assert source.index(f"DROP INDEX CONCURRENTLY IF EXISTS {name}") < source.index(
            f'"{name} "'
        )


def test_semantic_claim_ordering_index_rebuilds_same_name_relation() -> None:
    source = _ORDERING_REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_ORDERING_REVISION))
    name = "state_kv_operator_semantic_claim_order_idx"

    assert migration["down_revision"] == "core_semantic_transport_indexes_20260908"
    assert migration["migration_owner"] == "core-control-plane"
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" not in source
    assert source.index(f"DROP INDEX CONCURRENTLY IF EXISTS {name}") < source.index(f'"{name} "')
