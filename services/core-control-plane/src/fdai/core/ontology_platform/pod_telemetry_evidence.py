"""State-evidence classification for deterministic Pod telemetry paths."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.ontology_instance import OntologyLinkRecord
from fdai.shared.providers.state_evidence import StateFactMetadata


class TelemetrySegmentStatus(StrEnum):
    """Verification state of one required Pod telemetry path segment."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    STALE = "stale"
    MISSING = "missing"


class TelemetrySegmentKind(StrEnum):
    """Required segment identities in deterministic path order."""

    POD_SELECTED_BY_SERVICE = "pod_selected_by_service"
    SERVICE_EXPOSES_ENDPOINTS = "service_exposes_endpoints"
    OBSERVATION_TARGETS_POD = "observation_targets_pod"
    OBSERVATION_SAMPLE = "observation_sample"


class TelemetryPathSegment(ContractBase):
    """One evidence-bearing segment without an inferred health claim."""

    kind: TelemetrySegmentKind
    from_id: str | None
    to_id: str | None
    status: TelemetrySegmentStatus
    evidence_refs: tuple[str, ...]
    reasons: tuple[str, ...] = ()


class PodTelemetryPathResult(ContractBase):
    """Bounded telemetry path assessment that grants no action or health authority."""

    pod_id: str
    expected_cluster_ref: str
    segments: tuple[TelemetryPathSegment, ...]
    completeness: float
    complete: bool
    graph_receipt_ref: str
    evidence_refs: tuple[str, ...]
    claimed_health: Literal[False] = False
    execution_authority: Literal[False] = False


def telemetry_link_subject(link: OntologyLinkRecord) -> str:
    """Return the stable state-evidence subject for one typed graph link."""

    return f"link:{link.link_type}:{link.from_id}->{link.to_id}"


def telemetry_object_subject(object_id: str) -> str:
    """Return the stable state-evidence subject for one graph object."""

    return f"object:{object_id}"


def evaluate_state_fact_metadata(
    metadata: StateFactMetadata | None,
    *,
    cutoff: datetime,
) -> tuple[TelemetrySegmentStatus, tuple[str, ...]]:
    """Classify one immutable state fact without raising evidence authority."""

    if metadata is None:
        return TelemetrySegmentStatus.UNVERIFIED, ("state_evidence_missing",)
    evidence_cutoff = metadata.evidence_cutoff.astimezone(UTC)
    normalized_cutoff = cutoff.astimezone(UTC)
    if evidence_cutoff > normalized_cutoff:
        return TelemetrySegmentStatus.UNVERIFIED, ("evidence_after_cutoff",)
    if (normalized_cutoff - evidence_cutoff).total_seconds() > metadata.freshness_ceiling_seconds:
        return TelemetrySegmentStatus.STALE, ("state_evidence_stale",)
    reasons: list[str] = []
    if metadata.completeness < 1.0:
        reasons.append("state_evidence_incomplete")
    if metadata.synthetic:
        reasons.append("state_evidence_synthetic")
    reasons.extend(f"state_evidence_conflict:{item}" for item in metadata.conflicts)
    if reasons:
        return TelemetrySegmentStatus.UNVERIFIED, tuple(sorted(reasons))
    return TelemetrySegmentStatus.VERIFIED, ()


__all__ = [
    "PodTelemetryPathResult",
    "TelemetryPathSegment",
    "TelemetrySegmentKind",
    "TelemetrySegmentStatus",
    "evaluate_state_fact_metadata",
    "telemetry_link_subject",
    "telemetry_object_subject",
]
