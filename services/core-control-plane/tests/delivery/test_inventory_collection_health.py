"""Focused principal-safe inventory collection health projection tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fdai.delivery.inventory_collection_health import (
    CollectionCoverageGap,
    InventoryCollectionHealthInput,
    build_inventory_collection_health_projection,
)
from fdai.delivery.inventory_scheduler import (
    CollectionScheduleAction,
    CollectionScheduleDecision,
    ProviderPressure,
)

_MEASURED_AT = datetime(2026, 8, 22, 2, 0, tzinfo=UTC)


def _decision(
    *,
    action: CollectionScheduleAction = CollectionScheduleAction.WAIT,
    due_in_seconds: float = 60,
    reasons: tuple[str, ...] = ("healthy",),
) -> CollectionScheduleDecision:
    return CollectionScheduleDecision(
        action=action,
        due_in_seconds=due_in_seconds,
        interval_seconds=120,
        priority=10,
        concurrency_limit=4,
        freshness_available=True,
        reason_codes=reasons,
    )


def _health(**overrides: object) -> InventoryCollectionHealthInput:
    values: dict[str, object] = {
        "source_alias": "provider-delta",
        "measured_at": _MEASURED_AT,
        "cursor_lag_seconds": 0.0,
        "cursor_complete": True,
        "overlay_pending_resources": 0,
        "overlay_pending_relationships": 0,
        "overlay_complete": True,
        "evidence_age_seconds": 30.0,
        "target_freshness_seconds": 120,
        "max_staleness_seconds": 600,
        "visible_resource_count": 100,
        "visible_relationship_count": 200,
        "coverage_complete": True,
        "coverage_gaps": (),
        "provider_pressure": ProviderPressure.HEALTHY,
        "retry_after_seconds": None,
        "budget_remaining_ratio": 1.0,
        "schedule": _decision(),
    }
    values.update(overrides)
    return InventoryCollectionHealthInput(**values)  # type: ignore[arg-type]


def test_complete_health_exposes_only_aggregate_read_only_state() -> None:
    projection = build_inventory_collection_health_projection(_health())

    assert projection["cursor"] == {"state": "current", "lag_seconds": 0.0, "complete": True}
    assert projection["overlay"]["state"] == "closed"
    assert projection["freshness"]["status"] == "fresh"
    assert projection["coverage"]["status"] == "complete"
    assert projection["provider_pressure"]["state"] == "healthy"
    assert projection["next_action"]["action"] == "wait"
    assert projection["observation_authority"] is False
    assert projection["mutation_authority"] is False
    assert projection["execution_authority"] is False


def test_lag_overlay_partial_coverage_and_pressure_remain_explicit() -> None:
    projection = build_inventory_collection_health_projection(
        _health(
            cursor_lag_seconds=300.0,
            cursor_complete=False,
            overlay_pending_resources=3,
            overlay_pending_relationships=5,
            overlay_complete=False,
            evidence_age_seconds=200.0,
            coverage_complete=False,
            coverage_gaps=(
                CollectionCoverageGap.CURSOR_LAGGING,
                CollectionCoverageGap.OVERLAY_INCOMPLETE,
                CollectionCoverageGap.RELATIONSHIP_INCOMPLETE,
            ),
            provider_pressure=ProviderPressure.QUOTA_PRESSURE,
            budget_remaining_ratio=0.25,
            schedule=_decision(
                action=CollectionScheduleAction.COLLECT,
                due_in_seconds=0,
                reasons=("quota_pressure",),
            ),
        )
    )

    assert projection["cursor"]["state"] == "lagging"
    assert projection["overlay"]["state"] == "open"
    assert projection["freshness"]["status"] == "unknown"
    assert projection["coverage"]["status"] == "partial"
    assert projection["provider_pressure"] == {
        "state": "quota_pressure",
        "retry_after_seconds": None,
        "budget_remaining_ratio": 0.25,
    }
    assert projection["next_action"]["due"] is True
    assert projection["reason_codes"] == [
        "cursor_lagging",
        "overlay_incomplete",
        "relationship_incomplete",
        "quota_pressure",
    ]


def test_unavailable_inputs_never_become_zero_or_complete() -> None:
    projection = build_inventory_collection_health_projection(
        _health(
            cursor_lag_seconds=None,
            cursor_complete=False,
            evidence_age_seconds=None,
            visible_resource_count=None,
            visible_relationship_count=None,
            coverage_complete=False,
            coverage_gaps=(CollectionCoverageGap.SOURCE_UNAVAILABLE,),
            provider_pressure=ProviderPressure.CIRCUIT_OPEN,
            budget_remaining_ratio=None,
            schedule=_decision(reasons=("circuit_open",)),
        )
    )

    assert projection["cursor"] == {
        "state": "unavailable",
        "lag_seconds": None,
        "complete": False,
    }
    assert projection["freshness"]["status"] == "unavailable"
    assert projection["coverage"]["status"] == "unavailable"
    assert projection["coverage"]["visible_resources"] is None
    assert projection["coverage"]["visible_relationships"] is None


def test_projection_cannot_accept_raw_scope_endpoint_or_cursor_as_source_alias() -> None:
    for source_alias in (
        "https://management.example",
        "/subscriptions/example",
        "cursor:opaque-token",
    ):
        with pytest.raises(ValueError, match="sanitized identifier"):
            _health(source_alias=source_alias)


def test_projection_contains_no_principal_target_or_provider_identifiers() -> None:
    encoded = json.dumps(build_inventory_collection_health_projection(_health()), sort_keys=True)

    for forbidden in (
        "principal_id",
        "resource_id",
        "scope_id",
        "cursor_token",
        "endpoint",
        "subscription",
    ):
        assert forbidden not in encoded
