"""Durable operational activity projection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.activity_projection import durable_activity_projection

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def test_projection_merges_authoritative_sources_newest_first() -> None:
    payload = durable_activity_projection(
        inventory_rows=(
            {
                "id": "attempt-1",
                "status": "active",
                "source": "azure-resource-graph",
                "observation_kind": "observed",
                "started_at": NOW - timedelta(seconds=2),
                "completed_at": NOW - timedelta(seconds=1),
                "promoted_at": NOW - timedelta(seconds=1),
                "failure_code": None,
                "resource_count": 10,
                "link_count": 5,
            },
        ),
        ontology_rows=(
            {
                "value": {
                    "generation": "attempt-1",
                    "status": "available",
                    "dropped_reasons": [],
                },
                "updated_at": NOW,
            },
        ),
        read_rows=(
            {
                "key": "read-investigation-latency:sha256:abc",
                "tool_id": "query_resource_state",
                "transport": "provider",
                "operation_class": "resource_state",
                "sample": {
                    "succeeded": True,
                    "queue_duration_ms": 1,
                    "execution_duration_ms": 9,
                    "recorded_at": (NOW + timedelta(seconds=1)).isoformat(),
                },
            },
        ),
        limit=10,
    )

    items = payload["items"]
    assert isinstance(items, list)
    assert [item["kind"] for item in items] == [
        "current-state.read",
        "inventory.ontology-projection",
        "inventory.scan",
    ]
    assert items[-1]["evidence_count"] == 15
    assert all(item["execution_authority"] is False for item in items)


def test_projection_rejects_failed_inventory_without_reason() -> None:
    with pytest.raises(ValueError, match="failure code"):
        durable_activity_projection(
            inventory_rows=(
                {
                    "id": "attempt-1",
                    "status": "failed",
                    "source": "azure-resource-graph",
                    "started_at": NOW,
                    "completed_at": NOW,
                    "failure_code": None,
                    "resource_count": 0,
                    "link_count": 0,
                },
            ),
            ontology_rows=(),
            read_rows=(),
            limit=10,
        )


def test_projection_rejects_malformed_read_sample_instead_of_inventing_activity() -> None:
    with pytest.raises(ValueError, match="succeeded MUST be boolean"):
        durable_activity_projection(
            inventory_rows=(),
            ontology_rows=(),
            read_rows=(
                {
                    "key": "read-investigation-latency:sha256:abc",
                    "tool_id": "query_resource_state",
                    "sample": {"succeeded": "yes"},
                },
            ),
            limit=10,
        )
