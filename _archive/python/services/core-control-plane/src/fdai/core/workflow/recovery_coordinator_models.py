"""Immutable records, protocols, and configuration for workflow recovery.

Every type here is evidence or a declared collaboration seam. None of it
grants execution, approval, or effect-verification authority; the coordinator
in :mod:`fdai.core.workflow.recovery_coordinator` still re-verifies identity
separation, admission, and finality before any state change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
)
from fdai.core.workflow.recovery_effect_claim import (
    EffectCompletionClaim,
    EffectEvidenceRecord,
    FinalizedWatermark,
)
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot

DEFAULT_CLAIM_VALIDITY = timedelta(minutes=30)
DEFAULT_DISPATCH_LEASE = timedelta(minutes=5)


class RecoveryDisposition(StrEnum):
    """Caller-facing recovery outcome with no execution authority."""

    NOT_REQUIRED = "not_required"
    REJECTED = "rejected"
    IN_DOUBT = "in_doubt"
    OBSERVER_UNAVAILABLE = "observer_unavailable"
    EFFECT_UNVERIFIED = "effect_unverified"
    COMPLETED = "completed"
    REPLAYED = "replayed"


class RecoveryClaimDispatchState(StrEnum):
    """Exclusive ownership state of one pre-dispatch recovery claim."""

    UNCLAIMED = "unclaimed"
    IN_FLIGHT = "in_flight"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class RecoveryEffectClaimOutcome:
    """One effect-claim attempt with the exact reason it did not complete.

    A missing observer or intake binding is a readiness fact, not an unverified
    effect, so the two never collapse into the same silent disposition.
    """

    claim: EffectCompletionClaim | None
    reason: str
    disposition: RecoveryDisposition


@dataclass(frozen=True, slots=True)
class RecoveryCoordinationResult:
    """Immutable recovery evidence returned to the compensation caller."""

    disposition: RecoveryDisposition
    reason: str | None = None
    attempt_identity_digest: str | None = None
    claim_digest: str | None = None
    effect_claim_digest: str | None = None
    release_receipt_digest: str | None = None
    completion_digest: str | None = None
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False or self.approval_authority is not False:
            raise ValueError("recovery coordination result MUST NOT grant authority")

    @property
    def recovery_incomplete(self) -> bool:
        """Whether the hold MUST stay in force after this attempt."""

        return self.disposition not in {
            RecoveryDisposition.COMPLETED,
            RecoveryDisposition.REPLAYED,
            RecoveryDisposition.NOT_REQUIRED,
        }


@dataclass(frozen=True, slots=True)
class RecoveryEffectObservation:
    """One independent authoritative post-effect observation and its envelope."""

    evidence: EffectEvidenceRecord
    observer_identity: str
    provider_identity: str
    expected_effect_digest: str
    approved_envelope_digest: str
    action_digest: str
    evidence_window_start: datetime
    evidence_window_end: datetime
    watermarks: tuple[FinalizedWatermark, ...]
    success: bool

    def __post_init__(self) -> None:
        if not self.watermarks:
            raise ValueError("recovery effect observation requires at least one watermark")
        if self.evidence_window_end <= self.evidence_window_start:
            raise ValueError("recovery effect evidence window MUST be positive")

    @property
    def watermark_set_digest(self) -> str:
        """Bind every authoritative finality watermark into one digest."""

        return content_digest(
            [
                {
                    "source_id": watermark.source_id,
                    "watermark": watermark.watermark.astimezone(UTC).isoformat(),
                    "final": watermark.final,
                    "watermark_digest": watermark.watermark_digest,
                }
                for watermark in sorted(self.watermarks, key=lambda item: item.source_id)
            ]
        )

    @property
    def finalized(self) -> bool:
        """Whether every authoritative source reported finality."""

        return all(watermark.final for watermark in self.watermarks)


@runtime_checkable
class RecoveryDispatchPort(Protocol):
    """Dispatch one claimed recovery attempt and reconcile an in-doubt result."""

    async def dispatch_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        safeguard_bundle_digest: str,
        target_resource_id: str,
        params: Mapping[str, object],
        correlation_id: str,
    ) -> RecoveryDispatchResult: ...

    async def reconcile_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None: ...


@runtime_checkable
class RecoveryEffectObserver(Protocol):
    """Return one authoritative post-effect observation independent of dispatch."""

    async def observe_recovery_effect(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observed_at: datetime,
    ) -> RecoveryEffectObservation | None: ...


@runtime_checkable
class RecoveryEffectObservationIntake(Protocol):
    """Persist one independent authoritative post-effect observation.

    This is the explicit seam an observer that is independent of the executor
    and the provider writes through. An implementation persists evidence only;
    it never grants effect-verification authority and MUST refuse evidence the
    executor or provider owns.
    """

    async def record_observation(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observation: RecoveryEffectObservation,
    ) -> bool: ...


@runtime_checkable
class RecoverySafeguardBundleReader(Protocol):
    """Return the finalized safeguard bundle digest bound to one recovery attempt."""

    async def finalized_recovery_bundle_digest(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
    ) -> str | None: ...


@runtime_checkable
class RecoveryApprovalReader(Protocol):
    """Resolve the separate immutable human approval for one recovery attempt."""

    async def recovery_approval(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        process_id: str,
        target_resource_id: str,
    ) -> WorkflowApprovalSnapshot | None: ...


@runtime_checkable
class RecoveryApprovalRequester(Protocol):
    """Ask a separate human to decide one recovery attempt.

    Requesting is never granting: an implementation persists the pending ask
    in the human-decision journal and returns. Only a separate human decision
    recorded there can make the attempt admissible.
    """

    async def request_recovery_approval(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        process_id: str,
        target_resource_id: str,
        correlation_id: str,
    ) -> WorkflowApprovalSnapshot: ...


@dataclass(frozen=True, slots=True)
class RecoveryCoordinatorConfig:
    """Immutable identity and quorum configuration for the recovery path."""

    executor_identity: str
    source_revision: str
    quorum: int = 1
    no_self_approval: bool = True
    claim_validity: timedelta = DEFAULT_CLAIM_VALIDITY
    dispatch_lease: timedelta = DEFAULT_DISPATCH_LEASE

    def __post_init__(self) -> None:
        if not self.executor_identity.strip():
            raise ValueError("recovery coordinator requires an executor_identity")
        if not self.source_revision.strip() or len(self.source_revision) > 512:
            raise ValueError("recovery coordinator requires a bounded source_revision")
        if self.quorum < 1:
            raise ValueError("recovery coordinator quorum MUST be positive")
        if not self.no_self_approval:
            raise ValueError("recovery coordinator MUST keep no-self-approval enabled")
        if self.claim_validity <= timedelta(0):
            raise ValueError("recovery coordinator claim validity MUST be positive")
        if self.dispatch_lease <= timedelta(0):
            raise ValueError("recovery coordinator dispatch lease MUST be positive")


__all__ = [
    "DEFAULT_CLAIM_VALIDITY",
    "DEFAULT_DISPATCH_LEASE",
    "RecoveryApprovalReader",
    "RecoveryApprovalRequester",
    "RecoveryClaimDispatchState",
    "RecoveryCoordinationResult",
    "RecoveryCoordinatorConfig",
    "RecoveryDispatchPort",
    "RecoveryDisposition",
    "RecoveryEffectClaimOutcome",
    "RecoveryEffectObservation",
    "RecoveryEffectObservationIntake",
    "RecoveryEffectObserver",
    "RecoverySafeguardBundleReader",
]
