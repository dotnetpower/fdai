"""Publish bounded operational evidence without changing durable source ownership."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from fdai_service_contracts import (
    AgentOperationalActivity,
    OperationalActivityKind,
    OperationalActivityResultState,
    OperationalActivityResultUnit,
    OperationalActivityScopeClass,
    OperationalActivityStatus,
    OperationalActivitySummaryKey,
    OperationalFreshness,
)

from fdai.delivery.agent_activity import DEFAULT_STAGE_TOPIC
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.inventory import InventoryBatch
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventorySnapshotStore,
)

_LOGGER = logging.getLogger(__name__)


class EventBusOperationalActivityPublisher:
    """Publish live activity tips without turning broker delivery into durable truth."""

    def __init__(self, *, event_bus: EventBus, topic: str = DEFAULT_STAGE_TOPIC) -> None:
        if not topic:
            raise ValueError("topic MUST be non-empty")
        self._event_bus = event_bus
        self._topic = topic

    async def publish(self, activity: AgentOperationalActivity) -> bool:
        """Return false on broker failure while preserving the source transition."""
        try:
            await self._event_bus.publish(
                self._topic,
                activity.owner_agent,
                activity.model_dump(mode="json"),
            )
        except Exception:  # noqa: BLE001 - live tip cannot roll back durable source truth
            _LOGGER.warning(
                "operational_activity_publish_failed",
                extra={"kind": activity.kind.value, "status": activity.status.value},
                exc_info=True,
            )
            return False
        return True


class ObservedInventorySnapshotStore:
    """Delegate snapshot writes and publish activity only after durable transitions."""

    def __init__(
        self,
        *,
        store: InventorySnapshotStore,
        publisher: EventBusOperationalActivityPublisher,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._started: dict[str, float] = {}

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        attempt_id = await self._store.begin(manifest)
        self._started[attempt_id] = time.monotonic()
        await self._publisher.publish(
            _inventory_activity(
                attempt_id=attempt_id,
                source=manifest.source,
                status=OperationalActivityStatus.STARTED,
                freshness=OperationalFreshness.UNKNOWN,
            )
        )
        return attempt_id

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        await self._store.stage(attempt_id, batch)

    @property
    def stage_chunk(self) -> Callable[..., Awaitable[Mapping[str, Any]]] | None:
        """Expose durable chunk capability only when the wrapped store supports it."""
        return cast(
            Callable[..., Awaitable[Mapping[str, Any]]] | None,
            getattr(self._store, "stage_chunk", None),
        )

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        await self._store.promote(attempt_id, manifest)

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        await self._store.fail(attempt_id, failure)
        await self._publisher.publish(
            _inventory_activity(
                attempt_id=attempt_id,
                source="inventory-source",
                status=OperationalActivityStatus.FAILED,
                freshness=OperationalFreshness.UNAVAILABLE,
                duration_ms=self._elapsed_ms(attempt_id),
                reason_codes=(failure.code.value,),
            )
        )

    async def publish_terminal(
        self,
        *,
        attempt_id: str,
        source: str,
        active: bool,
        evidence_count: int,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        """Publish success only after the caller rereads the durable active pointer."""
        await self._publisher.publish(
            _inventory_activity(
                attempt_id=attempt_id,
                source=source,
                status=(
                    OperationalActivityStatus.COMPLETED
                    if active
                    else OperationalActivityStatus.SUPERSEDED
                ),
                freshness=(OperationalFreshness.FRESH if active else OperationalFreshness.UNKNOWN),
                evidence_count=evidence_count,
                duration_ms=self._elapsed_ms(attempt_id),
                reason_codes=reason_codes,
            )
        )

    def _elapsed_ms(self, attempt_id: str) -> int | None:
        started = self._started.pop(attempt_id, None)
        if started is None:
            return None
        return max(0, round((time.monotonic() - started) * 1000))


def _inventory_activity(
    *,
    attempt_id: str,
    source: str,
    status: OperationalActivityStatus,
    freshness: OperationalFreshness,
    evidence_count: int = 0,
    duration_ms: int | None = None,
    reason_codes: tuple[str, ...] = (),
) -> AgentOperationalActivity:
    observed_at = datetime.now(tz=UTC)
    if status is OperationalActivityStatus.STARTED:
        result_state = OperationalActivityResultState.NOT_RECORDED
    elif status is OperationalActivityStatus.FAILED:
        result_state = OperationalActivityResultState.UNAVAILABLE
    else:
        result_state = OperationalActivityResultState.MEASURED
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"inventory.scan:{attempt_id}:{status.value}",
        activity_instance_id=f"inventory.scan:{attempt_id}",
        idempotency_key=f"inventory.scan:{attempt_id}:{status.value}",
        kind=OperationalActivityKind.INVENTORY_SCAN,
        status=status,
        owner_agent="Huginn",
        producer="inventory-sync-job",
        observed_at=observed_at,
        source=source,
        freshness=freshness,
        evidence_count=evidence_count,
        duration_ms=duration_ms,
        correlation_id=attempt_id,
        reason_codes=reason_codes,
        summary_key=OperationalActivitySummaryKey.INVENTORY_COLLECTION,
        scope_class=OperationalActivityScopeClass.CONFIGURED_ESTATE,
        result_state=result_state,
        result_count=(
            evidence_count if result_state is OperationalActivityResultState.MEASURED else None
        ),
        result_unit=(
            OperationalActivityResultUnit.EVIDENCE_ITEMS
            if result_state is OperationalActivityResultState.MEASURED
            else None
        ),
        source_cutoff=(observed_at if status is not OperationalActivityStatus.STARTED else None),
        started_at=observed_at if status is OperationalActivityStatus.STARTED else None,
        completed_at=(observed_at if status is not OperationalActivityStatus.STARTED else None),
    )


def current_state_activity(
    *,
    correlation_id: str,
    status: OperationalActivityStatus,
    freshness: OperationalFreshness,
    evidence_count: int = 0,
    duration_ms: int | None = None,
    reason_codes: tuple[str, ...] = (),
) -> AgentOperationalActivity:
    """Build one privacy-bounded Heimdall read activity without target identity."""
    observed_at = datetime.now(tz=UTC)
    if status is OperationalActivityStatus.STARTED:
        result_state = OperationalActivityResultState.NOT_RECORDED
    elif status in {
        OperationalActivityStatus.COMPLETED,
        OperationalActivityStatus.SUPERSEDED,
    } or (status is OperationalActivityStatus.DEGRADED and evidence_count > 0):
        result_state = OperationalActivityResultState.MEASURED
    else:
        result_state = OperationalActivityResultState.UNAVAILABLE
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"current-state.read:{correlation_id}:{status.value}",
        activity_instance_id=f"current-state.read:{correlation_id}",
        idempotency_key=f"current-state.read:{correlation_id}:{status.value}",
        kind=OperationalActivityKind.CURRENT_STATE_READ,
        status=status,
        owner_agent="Heimdall",
        producer="core-control-plane",
        observed_at=observed_at,
        source="read-investigation",
        freshness=freshness,
        evidence_count=evidence_count,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
        reason_codes=reason_codes,
        summary_key=OperationalActivitySummaryKey.CURRENT_STATE_OBSERVATION,
        scope_class=OperationalActivityScopeClass.INVESTIGATION,
        result_state=result_state,
        result_count=(
            evidence_count if result_state is OperationalActivityResultState.MEASURED else None
        ),
        result_unit=(
            OperationalActivityResultUnit.EVIDENCE_ITEMS
            if result_state is OperationalActivityResultState.MEASURED
            else None
        ),
        source_cutoff=(observed_at if status is not OperationalActivityStatus.STARTED else None),
        started_at=observed_at if status is OperationalActivityStatus.STARTED else None,
        completed_at=(observed_at if status is not OperationalActivityStatus.STARTED else None),
    )


def ontology_projection_activity(
    *,
    generation: str,
    status: OperationalActivityStatus,
    freshness: OperationalFreshness,
    evidence_count: int,
    reason_codes: tuple[str, ...],
) -> AgentOperationalActivity:
    """Build one Heimdall-owned derived projection fact for a promoted generation."""
    observed_at = datetime.now(tz=UTC)
    result_state = (
        OperationalActivityResultState.MEASURED
        if status is OperationalActivityStatus.COMPLETED
        or status is OperationalActivityStatus.DEGRADED
        and evidence_count > 0
        else OperationalActivityResultState.UNAVAILABLE
    )
    recorded_evidence_count = (
        evidence_count if result_state is OperationalActivityResultState.MEASURED else 0
    )
    return AgentOperationalActivity(
        schema_version="1.3.0",
        activity_id=f"inventory.ontology-projection:{generation}:{status.value}",
        activity_instance_id=f"inventory.ontology-projection:{generation}",
        idempotency_key=f"inventory.ontology-projection:{generation}:{status.value}",
        kind=OperationalActivityKind.INVENTORY_ONTOLOGY_PROJECTION,
        status=status,
        owner_agent="Heimdall",
        producer="inventory-sync-job",
        observed_at=observed_at,
        source="inventory-ontology",
        freshness=freshness,
        evidence_count=recorded_evidence_count,
        correlation_id=generation,
        reason_codes=reason_codes,
        summary_key=OperationalActivitySummaryKey.ONTOLOGY_PROJECTION,
        scope_class=OperationalActivityScopeClass.CONFIGURED_ESTATE,
        result_state=result_state,
        result_count=(
            recorded_evidence_count
            if result_state is OperationalActivityResultState.MEASURED
            else None
        ),
        result_unit=(
            OperationalActivityResultUnit.EVIDENCE_ITEMS
            if result_state is OperationalActivityResultState.MEASURED
            else None
        ),
        source_cutoff=observed_at,
        completed_at=observed_at,
    )


__all__ = [
    "EventBusOperationalActivityPublisher",
    "ObservedInventorySnapshotStore",
    "current_state_activity",
    "ontology_projection_activity",
]
