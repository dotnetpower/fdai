"""Provider-routed Resource event history tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.resource_event_queries import (
    ResourceEventCollection,
    ResourceEventObservation,
)
from fdai.delivery.resource_event_history import CompositeResourceEventHistoryReader

NOW = datetime(2026, 8, 26, 13, 5, tzinfo=UTC)
RESOURCE_ID = "resource-example"


class _Reader:
    def __init__(self, family: str, *, minutes_ago: int) -> None:
        self.family = family
        self.minutes_ago = minutes_ago
        self.calls: list[tuple[str, ...]] = []

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        self.calls.append(event_families)
        occurred_at = NOW - timedelta(minutes=self.minutes_ago)
        return ResourceEventCollection(
            resource_ids=resource_ids,
            events=(
                ResourceEventObservation(
                    resource_id=RESOURCE_ID,
                    event_family=self.family,
                    event_kind="event",
                    status="observed",
                    classification="status_only",
                    occurred_at=occurred_at,
                    evidence_ref=f"{self.family}:{self.minutes_ago}",
                ),
            ),
            observed_at=NOW,
            complete=True,
            limitation=None,
            attempt_ref=f"{self.family}:attempt",
        )


async def test_composite_routes_families_and_merges_chronologically() -> None:
    health = _Reader("resource_event.resource_health", minutes_ago=5)
    kubernetes = _Reader("resource_event.kubernetes", minutes_ago=10)
    reader = CompositeResourceEventHistoryReader(
        readers={
            health.family: health,
            kubernetes.family: kubernetes,
        },
        now=lambda: NOW,
    )

    result = await reader.read_history(
        resource_ids=(RESOURCE_ID,),
        event_families=("resource_event.resource_health", "resource_event.kubernetes"),
        lookback_seconds=3600,
    )

    assert result.complete is True
    assert [event.event_family for event in result.events] == [
        "resource_event.kubernetes",
        "resource_event.resource_health",
    ]
    assert health.calls == [("resource_event.resource_health",)]
    assert kubernetes.calls == [("resource_event.kubernetes",)]


async def test_composite_keeps_bound_evidence_when_one_family_is_unavailable() -> None:
    health = _Reader("resource_event.resource_health", minutes_ago=5)
    reader = CompositeResourceEventHistoryReader(
        readers={health.family: health},
        now=lambda: NOW,
    )

    mixed = await reader.read_history(
        resource_ids=(RESOURCE_ID,),
        event_families=("resource_event.kubernetes", "resource_event.resource_health"),
        lookback_seconds=3600,
    )
    unavailable = await reader.read_history(
        resource_ids=(RESOURCE_ID,),
        event_families=("resource_event.kubernetes",),
        lookback_seconds=3600,
    )

    assert mixed.complete is False
    assert len(mixed.events) == 1
    assert mixed.limitation == "source_coverage_incomplete"
    assert unavailable.complete is False
    assert unavailable.events == ()
    assert unavailable.limitation == "source_unavailable"
