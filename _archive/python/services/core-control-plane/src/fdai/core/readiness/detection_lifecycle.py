"""Deterministic Kubernetes Pod detection projection for operator surfaces.

An operator reading a Pod detection surface needs four separable answers, and
collapsing any two of them produces a false statement:

- **Current state** - what the freshest complete observation says is true now.
- **Failure history** - what was already observed, which a later ``Running``
  read MUST NOT erase.
- **Recovery** - whether an independent observation verified the workload
  recovered, which is not implied by the absence of a new failure.
- **Evidence gaps** - what the projection could not observe, which is not the
  same as an observation that nothing happened.

This reducer therefore keeps the four apart and never upgrades one from
another. Every conclusion is copied from the canonical
:mod:`~fdai.core.ontology_platform.kubernetes_pod_replacement_evidence` and
:mod:`~fdai.core.ontology_platform.kubernetes_pod_recovery_evidence` reducers
through the typed analyzer receipt; nothing here re-derives completeness or
recovery, so a replay of the same records re-derives the same projection.

The projection fails closed. Missing, stale, incomplete, or conflicting
evidence yields ``unknown`` with an explicit gap rather than a reassuring
default, an uncertain or failed publication is itself a gap, and the snapshot
asserts no cause and carries no execution authority.

This module is deliberately absent from ``fdai.core.readiness.__init__``.
It depends on :mod:`fdai.core.ontology_platform`, which already depends on the
risk gate and the measurement package, and those depend on this package; an
eager re-export would close that cycle at interpreter start. Import
``fdai.core.readiness.detection_lifecycle`` directly.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryStatus,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementStatus,
)
from fdai.shared.contracts.models import ContractBase

DETECTION_LIFECYCLE_STATE_PREFIX = "runtime:detection-lifecycle:"
DETECTION_LIFECYCLE_SCHEMA_VERSION = 1
DEFAULT_LIFECYCLE_RETENTION = 32
DEFAULT_LIFECYCLE_FRESHNESS = timedelta(minutes=15)
_MAX_LIFECYCLE_RETENTION = 256

_FAILURE_SIGNALS = frozenset(
    {
        KubernetesPodReplacementStatus.CONTAINER_RESTART,
        KubernetesPodReplacementStatus.POD_REPLACEMENT,
        KubernetesPodReplacementStatus.ROLLOUT_REPLACEMENT,
    }
)


class DetectionPublicationState(StrEnum):
    """Projection mirror of the analyzer publication outcome.

    The delivery layer owns the runtime enum; this mirror keeps the operator
    contract inside Core so the projection stays importable by a surface that
    never runs a tick. ``test_detection_lifecycle`` pins the two value sets
    together, so a new delivery outcome cannot reach an operator unnamed.
    """

    PUBLISHED = "published"
    PUBLISHED_RECEIPT_UNRECORDED = "published_receipt_unrecorded"
    DUPLICATE_SUPPRESSED = "duplicate_suppressed"
    RECONCILED_DUPLICATE = "reconciled_duplicate"
    UNCERTAIN = "publish_uncertain"
    AWAITING_RECONCILIATION = "awaiting_reconciliation"
    FAILED = "failed"


class PodLifecycleCurrentState(StrEnum):
    """What the freshest complete observation says about the workload now."""

    RECOVERED = "recovered"
    """A complete, fresh observation verified the workload is serving again."""

    FAILING = "failing"
    """A complete, fresh observation classified a failure that is not closed."""

    UNKNOWN = "unknown"
    """No fresh complete observation exists; the surface MUST NOT reassure."""


class PodLifecycleRecoveryState(StrEnum):
    """Whether an independent observation verified recovery."""

    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    UNKNOWN = "unknown"


class DetectionEvidenceGap(StrEnum):
    """Why the projection cannot answer, kept apart from what it observed."""

    MISSING_EVIDENCE = "missing_evidence"
    """No retained record exists for the target at all."""

    STALE_EVIDENCE = "stale_evidence"
    """Every retained record is older than the freshness budget."""

    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    """The freshest record's canonical reducer reported incomplete evidence."""

    CONFLICTING_EVIDENCE = "conflicting_evidence"
    """Lifecycle or recovery sources disagreed for the freshest record."""

    UNASSESSED_FINDING = "unassessed_finding"
    """A retained record carries no canonical assessment to project."""

    DELIVERY_UNCERTAIN = "delivery_uncertain"
    """A retained finding MAY or MAY NOT have reached the control loop."""

    DELIVERY_FAILED = "delivery_failed"
    """A retained finding provably did not reach the control loop."""


class PodLifecycleDetectionRecord(ContractBase):
    """One retained analyzer finding, exactly as a canonical reducer left it."""

    resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=512)]
    signal: KubernetesPodReplacementStatus
    occurred_at: datetime
    recorded_at: datetime
    detection_latency_seconds: Annotated[float, Field(ge=0.0)]
    evidence_complete: bool
    recovery_closed: bool | None
    recovery_status: KubernetesPodRecoveryStatus | None
    publication: DetectionPublicationState
    assessed_by: Annotated[str | None, Field(min_length=1, max_length=256)] = None
    evidence_refs: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = ()
    evidence_gaps: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = ()

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pod lifecycle record timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_record(self) -> PodLifecycleDetectionRecord:
        if self.recorded_at < self.occurred_at:
            raise ValueError("Pod lifecycle record MUST NOT be recorded before it occurred")
        if self.recovery_closed is True and not self.evidence_complete:
            raise ValueError("Pod lifecycle record MUST NOT close recovery on incomplete evidence")
        return self


class PodLifecycleDetectionSnapshot(ContractBase):
    """Server-authored projection of one target's retained detection records.

    ``cause_claim_supported`` and ``execution_authority`` are fixed false. The
    projection reports lifecycle classification and verified recovery only; it
    names no cause and authorizes no change.
    """

    schema_version: Annotated[int, Field(ge=1, le=DETECTION_LIFECYCLE_SCHEMA_VERSION)] = (
        DETECTION_LIFECYCLE_SCHEMA_VERSION
    )
    resource_ref: Annotated[str, Field(min_length=1, max_length=512)]
    generated_at: datetime
    freshness_budget_seconds: Annotated[float, Field(gt=0.0)]
    current_state: PodLifecycleCurrentState
    current_state_observed_at: datetime | None
    current_signal: KubernetesPodReplacementStatus | None
    recovery_state: PodLifecycleRecoveryState
    recovery_verified_at: datetime | None
    failure_count: Annotated[int, Field(ge=0)]
    failures: tuple[PodLifecycleDetectionRecord, ...]
    retained_record_count: Annotated[int, Field(ge=0)]
    evidence_gaps: tuple[DetectionEvidenceGap, ...]
    evidence_gap_details: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = ()
    delivery_counts: dict[DetectionPublicationState, int]
    cause_claim_supported: bool = False
    execution_authority: bool = False

    @field_validator("generated_at")
    @classmethod
    def require_generated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Pod lifecycle projection time MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> PodLifecycleDetectionSnapshot:
        if self.cause_claim_supported or self.execution_authority:
            raise ValueError("Pod lifecycle projection MUST NOT claim cause or authority")
        if self.failure_count != len(self.failures):
            raise ValueError("Pod lifecycle failure count MUST match the retained failures")
        if self.retained_record_count < self.failure_count:
            raise ValueError("Pod lifecycle retention MUST include every retained failure")
        recovered = self.current_state is PodLifecycleCurrentState.RECOVERED
        if recovered and self.recovery_state is not PodLifecycleRecoveryState.VERIFIED:
            raise ValueError("Pod lifecycle recovery MUST be verified to report recovered")
        verified = self.recovery_state is PodLifecycleRecoveryState.VERIFIED
        if verified != (self.recovery_verified_at is not None):
            raise ValueError("Verified Pod lifecycle recovery MUST carry its observation time")
        return self


def reduce_pod_lifecycle_detection(
    records: tuple[PodLifecycleDetectionRecord, ...],
    *,
    resource_ref: str,
    generated_at: datetime,
    freshness_budget: timedelta = DEFAULT_LIFECYCLE_FRESHNESS,
    retention: int = DEFAULT_LIFECYCLE_RETENTION,
) -> PodLifecycleDetectionSnapshot:
    """Project one target's retained records without inferring a missing answer."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("Pod lifecycle projection time MUST be timezone-aware")
    if freshness_budget <= timedelta(0):
        raise ValueError("Pod lifecycle freshness budget MUST be positive")
    if retention < 1 or retention > _MAX_LIFECYCLE_RETENTION:
        raise ValueError("Pod lifecycle retention MUST be a bounded positive count")

    retained = retain_pod_lifecycle_records(records, resource_ref=resource_ref, retention=retention)
    gaps: list[DetectionEvidenceGap] = []
    details: list[str] = []
    delivery_counts = {state: 0 for state in DetectionPublicationState}
    for record in retained:
        delivery_counts[record.publication] += 1
        if record.publication in {
            DetectionPublicationState.UNCERTAIN,
            DetectionPublicationState.AWAITING_RECONCILIATION,
            DetectionPublicationState.PUBLISHED_RECEIPT_UNRECORDED,
        }:
            _add(gaps, DetectionEvidenceGap.DELIVERY_UNCERTAIN)
        elif record.publication is DetectionPublicationState.FAILED:
            _add(gaps, DetectionEvidenceGap.DELIVERY_FAILED)
        if record.assessed_by is None:
            _add(gaps, DetectionEvidenceGap.UNASSESSED_FINDING)

    failures = tuple(record for record in retained if record.signal in _FAILURE_SIGNALS)
    latest = retained[0] if retained else None
    fresh = latest is not None and generated_at - latest.recorded_at <= freshness_budget

    current_state = PodLifecycleCurrentState.UNKNOWN
    current_observed_at: datetime | None = None
    current_signal: KubernetesPodReplacementStatus | None = None
    recovery_state = PodLifecycleRecoveryState.UNKNOWN
    recovery_verified_at: datetime | None = None

    if latest is None:
        _add(gaps, DetectionEvidenceGap.MISSING_EVIDENCE)
    elif not fresh:
        _add(gaps, DetectionEvidenceGap.STALE_EVIDENCE)
    else:
        current_signal = latest.signal
        details.extend(latest.evidence_gaps)
        if latest.signal is KubernetesPodReplacementStatus.CONFLICTING_EVIDENCE:
            _add(gaps, DetectionEvidenceGap.CONFLICTING_EVIDENCE)
        elif latest.recovery_status is KubernetesPodRecoveryStatus.CONFLICTING_EVIDENCE:
            _add(gaps, DetectionEvidenceGap.CONFLICTING_EVIDENCE)
        elif not latest.evidence_complete:
            _add(gaps, DetectionEvidenceGap.INCOMPLETE_EVIDENCE)
        elif latest.recovery_closed is None:
            _add(gaps, DetectionEvidenceGap.UNASSESSED_FINDING)
        else:
            current_observed_at = latest.recorded_at
            if latest.recovery_closed:
                current_state = PodLifecycleCurrentState.RECOVERED
                recovery_state = PodLifecycleRecoveryState.VERIFIED
                recovery_verified_at = latest.recorded_at
            else:
                current_state = PodLifecycleCurrentState.FAILING
                recovery_state = PodLifecycleRecoveryState.NOT_VERIFIED

    return PodLifecycleDetectionSnapshot(
        resource_ref=resource_ref,
        generated_at=generated_at,
        freshness_budget_seconds=freshness_budget.total_seconds(),
        current_state=current_state,
        current_state_observed_at=current_observed_at,
        current_signal=current_signal,
        recovery_state=recovery_state,
        recovery_verified_at=recovery_verified_at,
        failure_count=len(failures),
        failures=failures,
        retained_record_count=len(retained),
        evidence_gaps=tuple(gaps),
        evidence_gap_details=tuple(dict.fromkeys(details)),
        delivery_counts=delivery_counts,
    )


def retain_pod_lifecycle_records(
    records: tuple[PodLifecycleDetectionRecord, ...],
    *,
    resource_ref: str,
    retention: int = DEFAULT_LIFECYCLE_RETENTION,
) -> tuple[PodLifecycleDetectionRecord, ...]:
    """Return this target's newest bounded records, deduplicated by key.

    A repeated tick re-observes the same window key. Keeping both copies would
    let one observation count twice in the delivery totals, so the newest
    record for a key replaces the older one instead of joining it. When two
    copies carry the same instant - a re-run of the same tick, or a
    reconciliation that resolves an uncertain publication - the later-supplied
    record wins, because the caller appends what it just observed after what it
    retained. A reconciled outcome therefore replaces the uncertain one it
    settles rather than being discarded as a tie.
    """

    if retention < 1 or retention > _MAX_LIFECYCLE_RETENTION:
        raise ValueError("Pod lifecycle retention MUST be a bounded positive count")
    by_key: dict[str, PodLifecycleDetectionRecord] = {}
    for record in records:
        if record.resource_ref != resource_ref:
            continue
        existing = by_key.get(record.idempotency_key)
        if existing is None or _order(record) >= _order(existing):
            by_key[record.idempotency_key] = record
    ordered = sorted(by_key.values(), key=_order, reverse=True)
    return tuple(ordered[:retention])


def pod_lifecycle_detection_state_key(resource_ref: str) -> str:
    """Return the stable tracked-state key for one target's projection."""

    if not resource_ref.strip():
        raise ValueError("Pod lifecycle resource_ref MUST be non-empty")
    digest = hashlib.sha256(resource_ref.encode("utf-8")).hexdigest()
    return f"{DETECTION_LIFECYCLE_STATE_PREFIX}{digest}"


def _order(record: PodLifecycleDetectionRecord) -> tuple[datetime, datetime, str]:
    return (record.recorded_at, record.occurred_at, record.idempotency_key)


def _add(gaps: list[DetectionEvidenceGap], gap: DetectionEvidenceGap) -> None:
    if gap not in gaps:
        gaps.append(gap)


__all__ = [
    "DEFAULT_LIFECYCLE_FRESHNESS",
    "DEFAULT_LIFECYCLE_RETENTION",
    "DETECTION_LIFECYCLE_SCHEMA_VERSION",
    "DETECTION_LIFECYCLE_STATE_PREFIX",
    "DetectionEvidenceGap",
    "DetectionPublicationState",
    "PodLifecycleCurrentState",
    "PodLifecycleDetectionRecord",
    "PodLifecycleDetectionSnapshot",
    "PodLifecycleRecoveryState",
    "pod_lifecycle_detection_state_key",
    "reduce_pod_lifecycle_detection",
    "retain_pod_lifecycle_records",
]
