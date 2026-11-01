"""Deterministic event-to-telemetry candidate routing for adaptive RCA."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.rca.discrimination import (
    HypothesisDiscriminationFrame,
    build_hypothesis_discrimination_frame,
)
from fdai.core.rca.telemetry_evidence import TelemetryMechanism
from fdai.core.rca.telemetry_recipes import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ReviewedTelemetryRecipeCatalog,
)

_EVENT_MECHANISMS: Final[tuple[tuple[tuple[str, ...], tuple[TelemetryMechanism, ...]], ...]] = (
    (
        ("429", "throttl", "quota"),
        (
            TelemetryMechanism.THROTTLING,
            TelemetryMechanism.FAILED_REQUESTS,
            TelemetryMechanism.DEPENDENCY_LATENCY,
        ),
    ),
    (
        ("latency", "slow", "timeout"),
        (
            TelemetryMechanism.DEPENDENCY_LATENCY,
            TelemetryMechanism.SLOW_TRACES,
            TelemetryMechanism.RESOURCE_SATURATION,
        ),
    ),
    (
        ("container", "kubernetes", "pod", "restart"),
        (
            TelemetryMechanism.CONTAINER_RESTARTS,
            TelemetryMechanism.ERROR_TIMELINE,
            TelemetryMechanism.RESOURCE_SATURATION,
        ),
    ),
    (
        ("shutdown", "dealloc", "power", "virtualmachine", "virtual_machine"),
        (
            TelemetryMechanism.GUEST_SHUTDOWN,
            TelemetryMechanism.ERROR_TIMELINE,
            TelemetryMechanism.RESOURCE_SATURATION,
        ),
    ),
    (
        ("500", "502", "503", "504", "error", "exception", "fail"),
        (
            TelemetryMechanism.FAILED_REQUESTS,
            TelemetryMechanism.ERROR_TIMELINE,
            TelemetryMechanism.DEPENDENCY_LATENCY,
        ),
    ),
    (
        ("cpu", "memory", "oom", "saturation", "disk", "pressure"),
        (
            TelemetryMechanism.RESOURCE_SATURATION,
            TelemetryMechanism.ERROR_TIMELINE,
            TelemetryMechanism.CONTAINER_RESTARTS,
        ),
    ),
)


def telemetry_hypothesis_id(mechanism: TelemetryMechanism) -> str:
    """Return the stable active-set id for one telemetry mechanism."""

    return f"telemetry:{mechanism.value}"


def telemetry_mechanisms_for_event(
    event_type: str,
    *,
    resource_type: str | None = None,
) -> tuple[TelemetryMechanism, ...]:
    """Select a bounded reviewed candidate family from deterministic event meaning."""

    normalized = f"{event_type} {resource_type or ''}".casefold()
    selected = {
        mechanism
        for markers, mechanisms in _EVENT_MECHANISMS
        if any(marker in normalized for marker in markers)
        for mechanism in mechanisms
    }
    if len(selected) < 2:
        selected = set(TelemetryMechanism)
    return tuple(sorted(selected, key=lambda item: item.value))


def build_initial_telemetry_frame(
    *,
    incident_id: str,
    graph_revision: str,
    evidence_cutoff: datetime,
    mechanisms: tuple[TelemetryMechanism, ...],
    catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
) -> HypothesisDiscriminationFrame:
    """Build the initial frame from a reviewed mechanism set."""

    if evidence_cutoff.tzinfo is None or evidence_cutoff.utcoffset() is None:
        raise ValueError("evidence_cutoff MUST be timezone-aware")
    cutoff_utc = evidence_cutoff.astimezone(UTC)
    hypothesis_ids = tuple(sorted({telemetry_hypothesis_id(item) for item in mechanisms}))
    active_set_digest = content_digest(
        {
            "incident_id": incident_id,
            "graph_revision": graph_revision,
            "evidence_cutoff": cutoff_utc.isoformat(),
            "active_hypothesis_ids": hypothesis_ids,
            "catalog_digest": catalog.catalog_digest,
        }
    )
    return build_hypothesis_discrimination_frame(
        incident_id=incident_id,
        graph_revision=graph_revision,
        evidence_cutoff=cutoff_utc,
        active_hypothesis_ids=hypothesis_ids,
        active_set_receipt_digest=active_set_digest,
        cost_model_digest=catalog.catalog_digest,
    )


__all__ = [
    "build_initial_telemetry_frame",
    "telemetry_hypothesis_id",
    "telemetry_mechanisms_for_event",
]
