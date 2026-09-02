"""Build the sanitized scheduled inventory health projection."""

from __future__ import annotations

from typing import Any

from fdai.delivery.inventory_collection_health import (
    CollectionCoverageGap,
    InventoryCollectionHealthInput,
    build_inventory_collection_health_projection,
)
from fdai.delivery.inventory_job_config import InventoryJobConfig
from fdai.delivery.inventory_scheduler import CollectionScheduleDecision
from fdai.delivery.persistence.postgres_inventory_reconciliation import (
    InventoryReconciliationHealthState,
)


def build_scheduled_collection_health_projection(
    config: InventoryJobConfig,
    *,
    health_state: InventoryReconciliationHealthState | None,
    decision: CollectionScheduleDecision | None,
) -> dict[str, Any] | None:
    """Return one aggregate health projection when both scheduled inputs exist."""

    if not isinstance(health_state, InventoryReconciliationHealthState) or not isinstance(
        decision, CollectionScheduleDecision
    ):
        return None
    policy = config.snapshot_policy(config.source_order[0])
    gaps: list[CollectionCoverageGap] = []
    if health_state.cursor_lag_seconds is None:
        gaps.append(CollectionCoverageGap.CURSOR_UNAVAILABLE)
    elif health_state.cursor_lag_seconds > policy.target_freshness_seconds:
        gaps.append(CollectionCoverageGap.CURSOR_LAGGING)
    overlay_complete = (
        health_state.overlay_resource_count == 0 and health_state.overlay_relationship_count == 0
    )
    if not overlay_complete:
        gaps.append(CollectionCoverageGap.OVERLAY_INCOMPLETE)
    if not health_state.coverage_complete:
        gaps.append(CollectionCoverageGap.SNAPSHOT_INCOMPLETE)
    if health_state.newer_failure:
        gaps.append(CollectionCoverageGap.SOURCE_UNAVAILABLE)
    return build_inventory_collection_health_projection(
        InventoryCollectionHealthInput(
            source_alias=policy.source_id,
            measured_at=health_state.measured_at,
            cursor_lag_seconds=health_state.cursor_lag_seconds,
            cursor_complete=health_state.cursor_complete,
            overlay_pending_resources=health_state.overlay_resource_count,
            overlay_pending_relationships=health_state.overlay_relationship_count,
            overlay_complete=overlay_complete,
            evidence_age_seconds=health_state.evidence_age_seconds,
            target_freshness_seconds=policy.target_freshness_seconds,
            max_staleness_seconds=policy.max_staleness_seconds,
            visible_resource_count=health_state.resource_count,
            visible_relationship_count=health_state.relationship_count,
            coverage_complete=health_state.coverage_complete and not health_state.newer_failure,
            coverage_gaps=tuple(gaps),
            provider_pressure=health_state.provider_pressure,
            retry_after_seconds=None,
            budget_remaining_ratio=None,
            schedule=decision,
        )
    )
