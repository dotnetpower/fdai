"""Enrich promoted inventory with authenticated runtime-call telemetry links."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from fdai.core.ontology_platform.runtime_call_projection import (
    RuntimeCallProjectionReason,
    project_runtime_call,
)
from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
    RuntimeCallTelemetryEnvelope,
    RuntimeCallTelemetryProducer,
)
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.contracts.models import OntologyRelease
from fdai.shared.providers.inventory import LinkRecord

RUNTIME_CALL_SOURCE_NAME = "runtime_call_graph"
_MAX_RUNTIME_CALL_OBSERVATIONS = 2_000
_RUNTIME_CALL_UNAVAILABLE_REASONS = frozenset(
    {
        "telemetry_deadline_exceeded",
        "telemetry_incomplete",
        "telemetry_scope_unavailable",
        "telemetry_source_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeCallTelemetryRecord:
    """One untrusted envelope paired with its separately supplied auth context."""

    envelope: RuntimeCallTelemetryEnvelope
    claimed_context: AuthenticatedRuntimeCallContext


@dataclass(frozen=True, slots=True)
class RuntimeCallTelemetryBatch:
    """One bounded complete or unavailable telemetry query result."""

    records: tuple[RuntimeCallTelemetryRecord, ...]
    observed_at: datetime | None
    complete: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if len(self.records) > _MAX_RUNTIME_CALL_OBSERVATIONS:
            raise ValueError(
                "runtime call telemetry batch MUST contain at most "
                f"{_MAX_RUNTIME_CALL_OBSERVATIONS} records"
            )
        if self.complete:
            if (
                self.observed_at is None
                or self.observed_at.tzinfo is None
                or self.reason is not None
            ):
                raise ValueError("complete runtime call telemetry MUST have only observed_at")
        elif self.records or self.observed_at is not None or not self.reason:
            raise ValueError("unavailable runtime call telemetry MUST have only a reason")
        if self.reason is not None and self.reason not in _RUNTIME_CALL_UNAVAILABLE_REASONS:
            raise ValueError("runtime call telemetry reason is not allowlisted")


class RuntimeCallTelemetrySource(Protocol):
    """Collect one bounded authenticated runtime-call telemetry batch."""

    async def collect(
        self,
        observation: PromotedInventoryObservation,
    ) -> RuntimeCallTelemetryBatch: ...


class UnavailableRuntimeCallInventoryEnricher:
    """Preserve explicit unavailability when no authenticated telemetry source is bound."""

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        """Add no edge and retain a sanitized unavailable source state."""

        return _unavailable(observation, reason="telemetry_source_unavailable")


class RuntimeCallInventoryEnricher:
    """Project a complete telemetry batch into the inventory single-writer input."""

    def __init__(
        self,
        *,
        source: RuntimeCallTelemetrySource,
        producer: RuntimeCallTelemetryProducer,
        ontology_release: OntologyRelease,
        scope_ref: str,
        endpoint_verifier_identity: str,
        endpoint_verifier_revision: str,
    ) -> None:
        for field_name, value in (
            ("scope_ref", scope_ref),
            ("endpoint_verifier_identity", endpoint_verifier_identity),
            ("endpoint_verifier_revision", endpoint_verifier_revision),
        ):
            if not value.strip() or len(value) > 512:
                raise ValueError(f"runtime call {field_name} MUST be bounded non-empty text")
        self._source = source
        self._producer = producer
        self._ontology_release = ontology_release
        self._scope_ref = scope_ref
        self._endpoint_verifier_identity = endpoint_verifier_identity
        self._endpoint_verifier_revision = endpoint_verifier_revision

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        """Return verified links or one explicit unavailable source state."""

        if not observation.complete:
            return _unavailable(observation, reason="inventory_generation_incomplete")
        try:
            batch = await self._source.collect(observation)
        except Exception:  # noqa: BLE001 - source details must not enter generation metadata
            return _unavailable(observation, reason="telemetry_source_unavailable")
        if not batch.complete:
            return _unavailable(observation, reason=batch.reason or "telemetry_source_unavailable")
        if batch.observed_at is None:  # pragma: no cover - guarded by batch validation
            return _unavailable(observation, reason="telemetry_source_unavailable")

        active_ids = frozenset(resource.resource_id for resource in observation.resources)
        projected: dict[tuple[str, str, str], LinkRecord] = {}
        for record in batch.records:
            try:
                typed = await self._producer.produce(
                    envelope=record.envelope,
                    claimed_context=record.claimed_context,
                )
                result = project_runtime_call(
                    typed,
                    active_resources=observation.resources,
                    readable_resource_ids=active_ids,
                    principal_scope_ref=self._scope_ref,
                    ontology_release=self._ontology_release,
                    inventory_generation=observation.generation,
                    evaluation_time=batch.observed_at,
                    verifier_identity=self._endpoint_verifier_identity,
                    verifier_revision=self._endpoint_verifier_revision,
                )
            except (TypeError, ValueError):
                return _unavailable(observation, reason="telemetry_authentication_failed")
            if result.reason is not RuntimeCallProjectionReason.PROJECTED or result.edge is None:
                return _unavailable(
                    observation,
                    reason=f"runtime_call_{result.reason.value}",
                )
            key = (result.edge.from_id, result.edge.link_type, result.edge.to_id)
            if key in projected:
                return _unavailable(observation, reason="runtime_call_duplicate_edge")
            projected[key] = result.edge

        existing_keys = {(link.from_id, link.link_type, link.to_id) for link in observation.links}
        if existing_keys.intersection(projected):
            return _unavailable(observation, reason="runtime_call_edge_conflict")
        edges = tuple(projected[key] for key in sorted(projected))
        return replace(
            observation,
            links=(*observation.links, *edges),
            source_states=(
                *observation.source_states,
                InventoryProjectionSourceState(
                    source=RUNTIME_CALL_SOURCE_NAME,
                    status=InventoryProjectionSourceStatus.AVAILABLE,
                    observed_at=batch.observed_at,
                    reason=None,
                ),
            ),
        )


def _unavailable(
    observation: PromotedInventoryObservation,
    *,
    reason: str,
) -> PromotedInventoryObservation:
    return replace(
        observation,
        source_states=(
            *observation.source_states,
            InventoryProjectionSourceState(
                source=RUNTIME_CALL_SOURCE_NAME,
                status=InventoryProjectionSourceStatus.UNAVAILABLE,
                observed_at=None,
                reason=reason,
            ),
        ),
    )


__all__ = [
    "RUNTIME_CALL_SOURCE_NAME",
    "RuntimeCallInventoryEnricher",
    "RuntimeCallTelemetryBatch",
    "RuntimeCallTelemetryRecord",
    "RuntimeCallTelemetrySource",
    "UnavailableRuntimeCallInventoryEnricher",
]
