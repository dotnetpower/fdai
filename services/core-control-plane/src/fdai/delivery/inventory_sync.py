"""Fail-closed full-snapshot coordinator with ordered source fallback."""

from __future__ import annotations

import logging
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
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
    ) -> None:
        self._store = store
        self._observer = promotion_observer
        self._relationship_mapping_catalog = relationship_mapping_catalog

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
        saw_final = False
        async for batch in stream:
            if saw_final:
                raise InventoryStreamError("inventory stream emitted data after final fence")
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
    "InventoryStreamError",
    "InventorySyncCoordinator",
    "classify_inventory_failure",
]
