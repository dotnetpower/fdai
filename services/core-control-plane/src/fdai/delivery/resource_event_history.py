"""Route bounded Resource event families to independently bound readers."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final

from fdai.core.ontology_platform.resource_event_queries import (
    RESOURCE_EVENT_MEASURE_CONCEPTS,
    ResourceEventCollection,
    ResourceEventCollectionReader,
    ResourceEventObservation,
)

_MAX_EVENTS: Final = 256


class CompositeResourceEventHistoryReader:
    """Merge independent family readers without widening secured Resource scope."""

    def __init__(
        self,
        *,
        readers: Mapping[str, ResourceEventCollectionReader],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        unknown = set(readers).difference(RESOURCE_EVENT_MEASURE_CONCEPTS)
        if unknown:
            raise ValueError("Resource event reader binding contains an unsupported family")
        self._readers: Final = dict(readers)
        self._now: Final = now or (lambda: datetime.now(UTC))

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        """Read each requested family and return one ordered bounded collection."""

        requested_families = tuple(sorted(set(event_families)))
        if (
            not requested_families
            or len(requested_families) != len(event_families)
            or any(family not in RESOURCE_EVENT_MEASURE_CONCEPTS for family in requested_families)
        ):
            raise ValueError("Resource event families MUST be supported and unique")
        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("Resource event composite clock MUST be timezone-aware")

        async def read_family(family: str) -> ResourceEventCollection | None:
            reader = self._readers.get(family)
            if reader is None:
                return None
            return await reader.read_history(
                resource_ids=resource_ids,
                event_families=(family,),
                lookback_seconds=lookback_seconds,
            )

        results = await asyncio.gather(
            *(read_family(family) for family in requested_families),
            return_exceptions=True,
        )
        events: list[ResourceEventObservation] = []
        attempt_refs: list[str] = []
        limitations: list[str] = []
        for family, result in zip(requested_families, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if result is None or isinstance(result, Exception):
                limitations.append("source_unavailable")
                continue
            if isinstance(result, BaseException):
                raise result
            if result.resource_ids != resource_ids:
                raise ValueError("Resource event reader changed the secured resource scope")
            if any(event.resource_id not in resource_ids for event in result.events):
                raise ValueError("Resource event reader returned evidence outside secured scope")
            if any(event.event_family != family for event in result.events):
                raise ValueError("Resource event reader returned an unrequested family")
            events.extend(result.events)
            attempt_refs.append(result.attempt_ref)
            if not result.complete:
                limitations.append(result.limitation or "source_coverage_incomplete")
        events.sort(key=lambda item: (item.occurred_at, item.evidence_ref))
        if len(events) > _MAX_EVENTS:
            events = events[:_MAX_EVENTS]
            limitations.append("result_limit")
        limitation = (
            limitations[0]
            if len(requested_families) == 1 and len(limitations) == 1
            else "source_coverage_incomplete"
            if limitations
            else None
        )
        material = "|".join(
            (
                *resource_ids,
                *requested_families,
                *attempt_refs,
                observed_at.isoformat(),
                limitation or "complete",
            )
        )
        return ResourceEventCollection(
            resource_ids=resource_ids,
            events=tuple(events),
            observed_at=observed_at,
            complete=limitation is None,
            limitation=limitation,
            attempt_ref=(
                f"composite-resource-event:{hashlib.sha256(material.encode()).hexdigest()}"
            ),
        )


__all__ = ["CompositeResourceEventHistoryReader"]
