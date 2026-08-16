"""Fail-closed full-snapshot coordinator with ordered source fallback."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import httpx

from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.delivery.kubernetes_relationships import project_kubernetes_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderRelationshipMappingCatalog,
)
from fdai.shared.providers.inventory import (
    Inventory,
    InventoryBatch,
    LinkRecord,
    RelationshipDrop,
    ResourceRecord,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
    InventorySnapshotStore,
    InventorySource,
    InventorySourcesExhaustedError,
    InventorySyncResult,
)

_LOG = logging.getLogger(__name__)

#: Accumulation ceilings for the optional observation handed to a derived read
#: model. They mirror the projection builder bounds so an oversized stream
#: degrades to an explicitly incomplete observation instead of exhausting memory.
_MAX_OBSERVED_RESOURCES = 50_000
_MAX_OBSERVED_LINKS = 200_000

#: Longest a source may go without producing anything. A provider that stops
#: making progress must fail its own attempt instead of holding the only writer
#: of the observed subgraph: an attempt left staging suppresses every later scan
#: until it is reaped, so an unbounded stall becomes an unbounded blackout.
DEFAULT_PROGRESS_DEADLINE_SECONDS = 900.0
#: Absolute ceiling for one attempt. The progress deadline alone cannot bound a
#: source that keeps producing just often enough to re-arm it. The value stays
#: below the reconciliation gate's 30-minute abandonment window so an attempt
#: always fails itself before the gate is entitled to start a second one.
DEFAULT_ATTEMPT_DEADLINE_SECONDS = 1500.0
#: Longest ceiling that still resolves before the abandonment window.
MAX_ATTEMPT_DEADLINE_SECONDS = 1740.0


@dataclass(frozen=True, slots=True)
class PromotedInventoryObservation:
    """One promoted snapshot handed to a derived read model.

    ``generation`` is the promoted snapshot identity. ``complete`` is ``False``
    when accumulation hit its ceiling, so a consumer cannot read absence from a
    truncated observation.
    """

    generation: str
    resources: tuple[ResourceRecord, ...]
    links: tuple[LinkRecord, ...]
    complete: bool
    relationship_drops: tuple[RelationshipDrop, ...] = ()
    recorded_at: datetime | None = None


#: Receives one promoted observation after the active pointer moves. The sink
#: owns a derived read model only; it never gains promotion authority.
InventoryPromotionObserver = Callable[[PromotedInventoryObservation], Awaitable[None]]


class InventoryStreamError(RuntimeError):
    """An inventory stream violated its atomic-fence contract."""


class InventorySyncCoordinator:
    """Stage one source at a time and promote only a complete stream."""

    def __init__(
        self,
        *,
        store: InventorySnapshotStore,
        promotion_observer: InventoryPromotionObserver | None = None,
        relationship_mapping_catalog: ProviderRelationshipMappingCatalog | None = None,
        progress_deadline_seconds: float = DEFAULT_PROGRESS_DEADLINE_SECONDS,
        attempt_deadline_seconds: float = DEFAULT_ATTEMPT_DEADLINE_SECONDS,
    ) -> None:
        if progress_deadline_seconds <= 0:
            raise ValueError("inventory progress_deadline_seconds MUST be > 0")
        if attempt_deadline_seconds < progress_deadline_seconds:
            raise ValueError(
                "inventory attempt_deadline_seconds MUST be >= progress_deadline_seconds"
            )
        if attempt_deadline_seconds > MAX_ATTEMPT_DEADLINE_SECONDS:
            raise ValueError(
                "inventory attempt_deadline_seconds MUST resolve before the "
                "abandonment window that lets a second attempt start"
            )
        self._store = store
        self._observer = promotion_observer
        self._relationship_mapping_catalog = relationship_mapping_catalog
        self._progress_deadline_seconds = progress_deadline_seconds
        self._attempt_deadline_seconds = attempt_deadline_seconds

    async def run(self, sources: Sequence[InventorySource]) -> InventorySyncResult:
        if not sources:
            raise ValueError("sources MUST NOT be empty")
        failures: list[InventoryAttemptFailure] = []
        for source in sources:
            attempt_id = await self._store.begin(source.manifest)
            observed = _ObservationAccumulator(
                enabled=self._observer is not None,
                relationship_mapping_catalog=self._relationship_mapping_catalog,
            )
            try:
                completed = await self._stage_stream(
                    attempt_id,
                    cast(Inventory, source.inventory).full_snapshot(),
                    observed,
                )
                manifest = InventoryCoverageManifest(
                    source=source.manifest.source,
                    scopes=source.manifest.scopes,
                    resource_types=source.manifest.resource_types,
                    observation_kind=source.manifest.observation_kind,
                    started_at=source.manifest.started_at,
                    completed_at=completed,
                    metadata=source.manifest.metadata,
                )
                await self._store.promote(attempt_id, manifest)
            except Exception as exc:  # noqa: BLE001 - source boundary, classified and retained
                failure = classify_inventory_failure(exc)
                await self._store.fail(attempt_id, failure)
                failures.append(failure)
                continue
            await self._notify_promotion(attempt_id, observed)
            return InventorySyncResult(
                attempt_id=attempt_id,
                source=source.name,
                failures=tuple(failures),
            )
        raise InventorySourcesExhaustedError(failures)

    async def _notify_promotion(self, attempt_id: str, observed: _ObservationAccumulator) -> None:
        """Hand the promoted observation to the derived read model.

        The promoted snapshot is already authoritative, so a failing derived
        projection is recorded and left behind rather than invalidating it.
        """
        if self._observer is None:
            return
        try:
            await self._observer(
                observed.result(
                    generation=attempt_id,
                    recorded_at=datetime.now(tz=UTC),
                )
            )
        except Exception:
            _LOG.exception(
                "inventory_promotion_observer_failed",
                extra={"generation": attempt_id},
            )

    async def _stage_stream(
        self,
        attempt_id: str,
        stream: AsyncIterator[InventoryBatch],
        observed: _ObservationAccumulator,
    ) -> datetime:
        """Stage one source stream under a no-progress deadline and a hard ceiling.

        Every received batch re-arms the no-progress deadline, so a slow source
        that keeps producing is allowed to finish while a silent one fails its
        own attempt. The ceiling still bounds a source that produces just often
        enough to keep re-arming it.
        """
        saw_final = False
        loop = asyncio.get_running_loop()
        ceiling_at = loop.time() + self._attempt_deadline_seconds

        def _next_deadline() -> float:
            return min(ceiling_at, loop.time() + self._progress_deadline_seconds)

        try:
            async with asyncio.timeout(self._attempt_deadline_seconds) as deadline:
                deadline.reschedule(_next_deadline())
                async for batch in stream:
                    deadline.reschedule(_next_deadline())
                    if saw_final:
                        raise InventoryStreamError(
                            "inventory stream emitted data after final fence"
                        )
                    if batch.final:
                        saw_final = True
                    if batch.resources or batch.links:
                        observed.add(batch)
                        await self._store.stage(
                            attempt_id,
                            InventoryBatch(
                                resources=batch.resources,
                                links=batch.links,
                                cursor=batch.cursor,
                            ),
                        )
        except TimeoutError as exc:
            # Name which bound fired: a stalled source and a source that is
            # merely too slow need different operator responses.
            reason = "absolute ceiling" if loop.time() >= ceiling_at else "no-progress deadline"
            raise InventoryStreamError(f"inventory source exceeded its {reason}") from exc
        finally:
            # A deadline cancels this task mid-iteration. An unclosed generator
            # would leave its provider requests running and spending quota after
            # the attempt that owned them has already failed. The Inventory
            # contract allows a plain iterator, which has nothing to close.
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()
        if not saw_final:
            raise InventoryStreamError("inventory stream ended before final fence")
        return datetime.now(tz=UTC)


class _ObservationAccumulator:
    """Collect streamed records for the optional derived projection only."""

    def __init__(
        self,
        *,
        enabled: bool,
        relationship_mapping_catalog: ProviderRelationshipMappingCatalog | None,
    ) -> None:
        self._enabled = enabled
        self._relationship_mapping_catalog = relationship_mapping_catalog
        self._resources: list[ResourceRecord] = []
        self._links: list[LinkRecord] = []
        self._relationship_drops: list[RelationshipDrop] = []
        self._truncated = False

    def add(self, batch: InventoryBatch) -> None:
        if not self._enabled or self._truncated:
            return
        if (
            len(self._resources) + len(batch.resources) > _MAX_OBSERVED_RESOURCES
            or len(self._links) + len(batch.links) > _MAX_OBSERVED_LINKS
        ):
            self._truncated = True
            self._resources.clear()
            self._links.clear()
            return
        self._resources.extend(batch.resources)
        self._links.extend(batch.links)
        self._relationship_drops.extend(batch.relationship_drops)

    def result(self, *, generation: str, recorded_at: datetime) -> PromotedInventoryObservation:
        projected = (
            project_kubernetes_relationships(
                self._resources,
                catalog=self._relationship_mapping_catalog,
                complete=not self._truncated,
            )
            if self._relationship_mapping_catalog is not None
            else None
        )
        verified = verify_inventory_relationships(
            generation=generation,
            resources=self._resources,
            links=((*self._links, *projected.links) if projected is not None else self._links),
            complete=not self._truncated,
            recorded_at=recorded_at,
            upstream_drops=(
                (*self._relationship_drops, *projected.dropped)
                if projected is not None
                else self._relationship_drops
            ),
        )
        return PromotedInventoryObservation(
            generation=generation,
            resources=tuple(self._resources),
            links=verified.links,
            complete=not self._truncated,
            relationship_drops=verified.dropped,
            recorded_at=recorded_at,
        )


def classify_inventory_failure(exc: Exception) -> InventoryAttemptFailure:
    """Map transport and contract failures to a bounded, secret-free code."""

    message = type(exc).__name__
    code = InventoryFailureCode.SOURCE_UNAVAILABLE
    if isinstance(exc, InventoryStreamError):
        code = InventoryFailureCode.PARTIAL
        message = str(exc)
    elif isinstance(exc, TimeoutError):
        # The attempt deadline cut the stream before its final fence, which is
        # the same absence of a completeness guarantee as a missing fence.
        code = InventoryFailureCode.PARTIAL
        message = "inventory source attempt exceeded its deadline"
    elif isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError)):
        cause = exc.__cause__
        code = (
            InventoryFailureCode.DNS_FAILED
            if isinstance(cause, socket.gaierror)
            else InventoryFailureCode.NETWORK_BLOCKED
        )
    else:
        text = str(exc).lower()
        if "http 401" in text or "token" in text or "identity" in text:
            code = InventoryFailureCode.TOKEN_FAILED
        elif "http 403" in text or "forbidden" in text:
            code = InventoryFailureCode.FORBIDDEN
        elif "http 429" in text or "throttl" in text:
            code = InventoryFailureCode.THROTTLED
        elif "pagination cap" in text or "partial" in text:
            code = InventoryFailureCode.PARTIAL
        elif isinstance(exc, (ValueError, TypeError)):
            code = InventoryFailureCode.INVALID_DATA
    return InventoryAttemptFailure(code=code, message=message[:200])


__all__ = [
    "DEFAULT_ATTEMPT_DEADLINE_SECONDS",
    "DEFAULT_PROGRESS_DEADLINE_SECONDS",
    "MAX_ATTEMPT_DEADLINE_SECONDS",
    "InventoryStreamError",
    "InventorySyncCoordinator",
    "classify_inventory_failure",
]
