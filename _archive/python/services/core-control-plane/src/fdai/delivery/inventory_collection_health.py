"""Project aggregate inventory collection health without target identities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.delivery.inventory_scheduler import (
    CollectionScheduleDecision,
    ProviderPressure,
)

_SOURCE_ALIAS_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_MAX_AGGREGATE_COUNT = 1_000_000_000


class CollectionFreshnessStatus(StrEnum):
    """Summarize evidence age without claiming source availability."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class CollectionCoverageStatus(StrEnum):
    """Summarize whether aggregate source coverage is complete."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class CollectionCoverageGap(StrEnum):
    """Expose bounded gap categories instead of provider or target text."""

    CURSOR_UNAVAILABLE = "cursor_unavailable"
    CURSOR_LAGGING = "cursor_lagging"
    OVERLAY_INCOMPLETE = "overlay_incomplete"
    SOURCE_TRUNCATED = "source_truncated"
    SOURCE_UNAVAILABLE = "source_unavailable"
    RELATIONSHIP_INCOMPLETE = "relationship_incomplete"
    SNAPSHOT_INCOMPLETE = "snapshot_incomplete"


@dataclass(frozen=True, slots=True)
class InventoryCollectionHealthInput:
    """Carry aggregate source state with no cursor token or target identity."""

    source_alias: str
    measured_at: datetime
    cursor_lag_seconds: float | None
    cursor_complete: bool
    overlay_pending_resources: int
    overlay_pending_relationships: int
    overlay_complete: bool
    evidence_age_seconds: float | None
    target_freshness_seconds: int
    max_staleness_seconds: int
    visible_resource_count: int | None
    visible_relationship_count: int | None
    coverage_complete: bool
    coverage_gaps: tuple[CollectionCoverageGap, ...]
    provider_pressure: ProviderPressure
    retry_after_seconds: float | None
    budget_remaining_ratio: float | None
    schedule: CollectionScheduleDecision

    def __post_init__(self) -> None:
        if _SOURCE_ALIAS_PATTERN.fullmatch(self.source_alias) is None:
            raise ValueError("inventory collection source_alias MUST be a sanitized identifier")
        if self.measured_at.tzinfo is None:
            raise ValueError("inventory collection measured_at MUST be timezone-aware")
        for name in ("cursor_lag_seconds", "evidence_age_seconds", "retry_after_seconds"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"inventory collection {name} MUST NOT be negative")
        for name in ("target_freshness_seconds", "max_staleness_seconds"):
            value = getattr(self, name)
            if value < 1:
                raise ValueError(f"inventory collection {name} MUST be positive")
        if self.target_freshness_seconds > self.max_staleness_seconds:
            raise ValueError("target freshness MUST NOT exceed maximum staleness")
        for name in (
            "overlay_pending_resources",
            "overlay_pending_relationships",
            "visible_resource_count",
            "visible_relationship_count",
        ):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= _MAX_AGGREGATE_COUNT:
                raise ValueError(f"inventory collection {name} is outside the aggregate bound")
        if self.budget_remaining_ratio is not None and not (
            0.0 <= self.budget_remaining_ratio <= 1.0
        ):
            raise ValueError("inventory collection budget_remaining_ratio MUST be in [0, 1]")


def build_inventory_collection_health_projection(
    health: InventoryCollectionHealthInput,
) -> dict[str, Any]:
    """Return a bounded read-only projection safe for an authorized principal.

    Authorization remains at the Operator boundary. This projection deliberately excludes
    principal ids, provider endpoints, scope ids, cursor tokens, and resource identities.
    """

    cursor_state = "unavailable"
    if health.cursor_lag_seconds is not None:
        cursor_state = (
            "current" if health.cursor_complete and health.cursor_lag_seconds == 0 else "lagging"
        )
    overlay_open = (
        health.overlay_pending_resources > 0
        or health.overlay_pending_relationships > 0
        or not health.overlay_complete
    )
    freshness = _freshness(health, overlay_open=overlay_open)
    coverage = _coverage(health)
    reason_codes = tuple(
        dict.fromkeys(
            (
                *(gap.value for gap in health.coverage_gaps),
                *health.schedule.reason_codes,
            )
        )
    )
    return {
        "schema_version": "1.0.0",
        "source_alias": health.source_alias,
        "measured_at": health.measured_at.isoformat(),
        "cursor": {
            "state": cursor_state,
            "lag_seconds": health.cursor_lag_seconds,
            "complete": health.cursor_complete,
        },
        "overlay": {
            "state": "open" if overlay_open else "closed",
            "pending_resources": health.overlay_pending_resources,
            "pending_relationships": health.overlay_pending_relationships,
            "complete": health.overlay_complete,
        },
        "freshness": {
            "status": freshness.value,
            "age_seconds": health.evidence_age_seconds,
            "target_seconds": health.target_freshness_seconds,
            "maximum_staleness_seconds": health.max_staleness_seconds,
        },
        "coverage": {
            "status": coverage.value,
            "complete": health.coverage_complete,
            "visible_resources": health.visible_resource_count,
            "visible_relationships": health.visible_relationship_count,
            "gap_codes": [gap.value for gap in health.coverage_gaps],
        },
        "provider_pressure": {
            "state": health.provider_pressure.value,
            "retry_after_seconds": health.retry_after_seconds,
            "budget_remaining_ratio": health.budget_remaining_ratio,
        },
        "next_action": {
            "action": health.schedule.action.value,
            "due": health.schedule.due,
            "due_in_seconds": health.schedule.due_in_seconds,
            "interval_seconds": health.schedule.interval_seconds,
            "priority": health.schedule.priority,
            "concurrency_limit": health.schedule.concurrency_limit,
            "reason_codes": list(health.schedule.reason_codes),
        },
        "reason_codes": list(reason_codes),
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }


def _freshness(
    health: InventoryCollectionHealthInput,
    *,
    overlay_open: bool,
) -> CollectionFreshnessStatus:
    if health.evidence_age_seconds is None:
        return CollectionFreshnessStatus.UNAVAILABLE
    if overlay_open or not health.cursor_complete:
        return CollectionFreshnessStatus.UNKNOWN
    if health.evidence_age_seconds > health.max_staleness_seconds:
        return CollectionFreshnessStatus.STALE
    if health.evidence_age_seconds > health.target_freshness_seconds:
        return CollectionFreshnessStatus.STALE
    return CollectionFreshnessStatus.FRESH


def _coverage(health: InventoryCollectionHealthInput) -> CollectionCoverageStatus:
    if health.visible_resource_count is None or health.visible_relationship_count is None:
        return CollectionCoverageStatus.UNAVAILABLE
    if health.coverage_complete and not health.coverage_gaps:
        return CollectionCoverageStatus.COMPLETE
    return CollectionCoverageStatus.PARTIAL


__all__ = [
    "CollectionCoverageGap",
    "CollectionCoverageStatus",
    "CollectionFreshnessStatus",
    "InventoryCollectionHealthInput",
    "build_inventory_collection_health_projection",
]
