"""Replayable operational-state observations, never a failure-cause judgment."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.state_evidence import StateFactLane, StateFactMetadata

RESOURCE_AVAILABILITY_ASSESSOR = "core.investigation.resource_availability_evidence"


class ResourceOperationalState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class AvailabilityUnavailableReason(StrEnum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    AUTHORIZATION_DENIED = "authorization_denied"
    RESOURCE_MISSING = "resource_missing"
    IDENTITY_MISMATCH = "identity_mismatch"
    GENERATION_CHANGED = "generation_changed"
    UNSUPPORTED_RESOURCE_TYPE = "unsupported_resource_type"
    OBSERVATION_INCOMPLETE = "observation_incomplete"


def require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("availability timestamps MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class PlannedStopWindow:
    """An attributed exact-resource declaration, not execution authorization."""

    resource_ref: str
    since: datetime
    until: datetime
    evidence_ref: str
    maintenance: bool = False

    def __post_init__(self) -> None:
        require_aware(self.since)
        require_aware(self.until)
        if self.since >= self.until or not self.resource_ref or not self.evidence_ref:
            raise ValueError("planned stop MUST have an exact resource, reference and time window")


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityPolicy:
    """Explicit monitoring opt-in; absence of an expectation never means running."""

    resource_types: frozenset[str]
    expected_state: ResourceOperationalState | None = None
    expectation_ref: str | None = None
    planned_stops: tuple[PlannedStopWindow, ...] = ()
    max_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_types", frozenset(self.resource_types))
        object.__setattr__(self, "planned_stops", tuple(self.planned_stops))
        if not self.resource_types or any(not item.strip() for item in self.resource_types):
            raise ValueError("availability policy MUST explicitly select resource types")
        if not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0:
            raise ValueError("availability freshness MUST be finite and positive")
        if self.expected_state is not None and (
            not isinstance(self.expected_state, ResourceOperationalState)
            or self.expected_state
            not in {
                ResourceOperationalState.RUNNING,
                ResourceOperationalState.STOPPED,
            }
            or not self.expectation_ref
        ):
            raise ValueError("expected operational state MUST have declaration provenance")


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityEvidence:
    """One retained inventory observation with independent collection disposition."""

    resource_ref: str
    resource_type: str
    scope_ref: str
    state: ResourceOperationalState
    observed_at: datetime | None
    recorded_at: datetime
    source_revision: str | None
    evidence_ref: str | None
    unavailable_reason: AvailabilityUnavailableReason | None = None
    state_metadata: StateFactMetadata | None = None

    def __post_init__(self) -> None:
        require_aware(self.recorded_at)
        if self.observed_at is not None:
            require_aware(self.observed_at)
        if not self.resource_ref or not self.resource_type or not self.scope_ref:
            raise ValueError("availability evidence MUST bind resource, type and scope")
        if not isinstance(self.state, ResourceOperationalState):
            raise ValueError("availability state MUST be typed")
        if self.unavailable_reason is not None and not isinstance(
            self.unavailable_reason, AvailabilityUnavailableReason
        ):
            raise ValueError("availability collection disposition MUST be typed")


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityAssessment:
    evidence_complete: bool
    recovery_closed: bool | None
    status: str
    recovery_status: str | None = None
    evidence_gaps: tuple[str, ...] = ()


def assess_resource_availability(
    evidence: ResourceAvailabilityEvidence,
    *,
    resource_ref: str,
    resource_type: str,
    scope_ref: str,
    since: datetime,
    until: datetime,
    policy: ResourceAvailabilityPolicy,
    prior_status: str | None = None,
    prior_fault_at: datetime | None = None,
    prior_finding_ref: str | None = None,
) -> ResourceAvailabilityAssessment:
    """Reduce only exact, fresh facts; planned stops cannot prove recovery."""

    require_aware(since)
    require_aware(until)
    if since >= until:
        raise ValueError("availability window MUST be positive")
    if prior_fault_at is not None:
        require_aware(prior_fault_at)
    gap: str | None = None
    if resource_type not in policy.resource_types:
        gap = "not_monitored"
    elif (evidence.resource_ref, evidence.resource_type, evidence.scope_ref) != (
        resource_ref,
        resource_type,
        scope_ref,
    ):
        gap = "identity_mismatch"
    elif evidence.unavailable_reason is not None:
        gap = evidence.unavailable_reason.value
    elif not evidence.source_revision or not evidence.evidence_ref:
        gap = "provenance_missing"
    elif evidence.state_metadata is not None and (
        evidence.state_metadata.lane is not StateFactLane.OBSERVED
        or evidence.state_metadata.synthetic
        or evidence.state_metadata.conflicts
        or evidence.state_metadata.completeness < 1.0
        or evidence.state_metadata.effective_at != evidence.observed_at
        or evidence.state_metadata.evidence_cutoff > until
        or evidence.state_metadata.recorded_at > until
    ):
        gap = "state_observation_unverified"
    elif evidence.observed_at is None:
        gap = "observation_time_missing"
    elif evidence.observed_at > until or evidence.observed_at > evidence.recorded_at:
        gap = "observation_time_invalid"
    elif evidence.observed_at < since or (until - evidence.observed_at).total_seconds() > min(
        policy.max_age_seconds,
        evidence.state_metadata.freshness_ceiling_seconds
        if evidence.state_metadata is not None
        else policy.max_age_seconds,
    ):
        gap = "stale"
    elif evidence.state is ResourceOperationalState.UNKNOWN:
        gap = "unknown"
    if gap:
        return ResourceAvailabilityAssessment(
            evidence_complete=False,
            recovery_closed=None,
            status=gap,
            evidence_gaps=(gap,),
        )

    planned = next(
        (
            window
            for window in policy.planned_stops
            if window.resource_ref == resource_ref
            and evidence.observed_at is not None
            and window.since <= evidence.observed_at <= until < window.until
        ),
        None,
    )
    if evidence.state is ResourceOperationalState.STOPPED:
        if planned is not None:
            status = "maintenance_stop_observed" if planned.maintenance else "planned_stop_observed"
        elif policy.expected_state is ResourceOperationalState.RUNNING:
            status = "expected_running_not_observed"
        elif policy.expected_state is ResourceOperationalState.STOPPED:
            status = "expected_stop_observed"
        else:
            status = "stop_observed"
    elif policy.expected_state is ResourceOperationalState.STOPPED:
        status = "expected_stop_not_observed"
    else:
        status = "running_observed"
    recovery_pairs = {
        "stop_observed": "running_observed",
        "expected_running_not_observed": "running_observed",
        "expected_stop_not_observed": "expected_stop_observed",
    }
    recovered = (
        prior_finding_ref is not None
        and prior_fault_at is not None
        and evidence.observed_at is not None
        and evidence.observed_at > prior_fault_at
        and recovery_pairs.get(prior_status or "") == status
    )
    return ResourceAvailabilityAssessment(
        evidence_complete=True,
        recovery_closed=recovered
        if prior_finding_ref
        else (False if status in recovery_pairs else None),
        status=status,
        recovery_status="expected_state_observed" if recovered else "not_verified",
    )
