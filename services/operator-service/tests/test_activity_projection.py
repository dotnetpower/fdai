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
                    "correlation_ref": "read-correlation:one",
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
    assert items[0]["activity_id"] == "current-state.read:read-correlation:one:completed"


def test_projects_durable_observation_campaign_activity() -> None:
    payload = durable_activity_projection(
        inventory_rows=(),
        ontology_rows=(),
        read_rows=(),
        observation_rows=(
            {
                "key": "observation-campaign:source:resource-health",
                "value": {
                    "source_id": "resource-health",
                    "domain": "resource-health",
                    "campaign_id": "campaign-1",
                    "status": "completed",
                    "freshness": "fresh",
                    "evidence_count": 2,
                    "duration_ms": 50,
                    "reason_codes": [],
                    "completed_at": "2026-08-14T00:00:00+00:00",
                },
                "updated_at": "2026-08-14T00:00:00+00:00",
            },
        ),
        limit=10,
    )

    item = payload["items"][0]
    assert item["schema_version"] == "1.1.0"
    assert item["kind"] == "observation"
    assert item["observation_domain"] == "resource-health"
    assert item["owner_agent"] == "Heimdall"
    assert item["activity_id"] == "observation:resource-health:campaign-1:completed"


def test_projects_in_progress_observation_without_terminal_fields() -> None:
    payload = durable_activity_projection(
        inventory_rows=(),
        ontology_rows=(),
        read_rows=(),
        observation_rows=(
            {
                "key": "observation-campaign:source:activity-log",
                "value": {
                    "source_id": "activity-log",
                    "domain": "activity-log",
                    "campaign_id": "campaign-active",
                    "status": "started",
                    "freshness": "unknown",
                    "evidence_count": 0,
                    "reason_codes": [],
                    "started_at": "2026-08-14T00:00:00+00:00",
                },
                "updated_at": "2026-08-14T00:00:00+00:00",
            },
        ),
        limit=10,
    )

    item = payload["items"][0]
    assert item["status"] == "started"
    assert item["freshness"] == "unknown"
    assert item["duration_ms"] is None
    assert item["activity_id"] == "observation:activity-log:campaign-active:started"


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


def test_projection_preserves_inventory_with_out_of_range_duration() -> None:
    payload = durable_activity_projection(
        inventory_rows=(
            {
                "id": "attempt-long",
                "status": "active",
                "source": "azure-resource-graph",
                "started_at": NOW - timedelta(days=14),
                "completed_at": NOW,
                "failure_code": None,
                "resource_count": 10,
                "link_count": 5,
            },
        ),
        ontology_rows=(),
        read_rows=(),
        limit=10,
    )

    item = payload["items"][0]
    assert item["status"] == "completed"
    assert item["duration_ms"] is None
    assert item["reason_codes"] == ["duration_out_of_range"]


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


def test_projection_deduplicates_live_identity_and_keeps_newest_read_sample() -> None:
    read_rows = tuple(
        {
            "key": "read-investigation-latency:sha256:abc",
            "tool_id": "get_resource_state",
            "transport": "provider",
            "operation_class": "resource_state",
            "sample": {
                "succeeded": True,
                "queue_duration_ms": 1,
                "execution_duration_ms": duration,
                "recorded_at": (NOW + timedelta(seconds=offset)).isoformat(),
                "correlation_ref": "read-correlation:same",
            },
        }
        for offset, duration in ((2, 20), (1, 10))
    )

    payload = durable_activity_projection(
        inventory_rows=(),
        ontology_rows=(),
        read_rows=read_rows,
        limit=10,
    )

    items = payload["items"]
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["activity_id"] == "current-state.read:read-correlation:same:completed"
    assert items[0]["duration_ms"] == 21
