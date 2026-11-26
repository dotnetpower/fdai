"""Exact transition plans for atomic post-release closure persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    ReservationState,
    complete_reservation,
    complete_reservation_from_verifier,
    quarantine_reservation,
    validate_reservation_transition,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureIdentity,
    PostReleaseClosureOutcome,
    PostReleaseClosurePhase,
    PostReleaseClosureRecord,
    PostReleaseContinuityState,
    PostReleaseReconciliationEvidence,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
    create_post_release_closure_record,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    PreReleaseContinuityState,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_support import utc
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    close_target_fence_after_release,
    validate_target_fence_transition,
)
from fdai.shared.providers.resource_lock import (
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)


@dataclass(frozen=True, slots=True)
class PostReleaseClosurePlan:
    """Exact predecessor and successor records for one atomic database write."""

    pre_release_record: SafeguardDispatchEvidenceRecord
    prior_reservation_record: IdempotencyReservationRecord
    reservation_record: IdempotencyReservationRecord
    prior_fence_record: TargetDispatchFenceRecord
    fence_record: TargetDispatchFenceRecord
    release_receipt: ResourceLockReleaseReceipt
    record: PostReleaseClosureRecord

    def __post_init__(self) -> None:
        if (
            type(self.pre_release_record) is not SafeguardDispatchEvidenceRecord
            or self.pre_release_record.state is not SafeguardDispatchEvidenceState.PRE_RELEASE
        ):
            raise ValueError("post-release plan requires exact pre-release evidence")
        for value, expected, name in (
            (
                self.prior_reservation_record,
                IdempotencyReservationRecord,
                "reservation predecessor",
            ),
            (self.reservation_record, IdempotencyReservationRecord, "reservation successor"),
            (self.prior_fence_record, TargetDispatchFenceRecord, "fence predecessor"),
            (self.fence_record, TargetDispatchFenceRecord, "fence successor"),
            (self.release_receipt, ResourceLockReleaseReceipt, "release receipt"),
            (self.record, PostReleaseClosureRecord, "closure record"),
        ):
            if type(value) is not expected:
                raise ValueError(f"post-release plan {name} is invalid")
        _validate_plan_bindings(self)


def build_initial_post_release_closure(
    *,
    pre_release_record: SafeguardDispatchEvidenceRecord,
    reservation_record: IdempotencyReservationRecord,
    release_pending_fence: TargetDispatchFenceRecord,
    release_receipt: ResourceLockReleaseReceipt,
    closed_at: datetime,
    force_quarantine: bool = False,
) -> PostReleaseClosurePlan:
    """Build one initial resolved or quarantined atomic closure plan."""

    if type(reservation_record) is not IdempotencyReservationRecord:
        raise ValueError("post-release closure requires exact reservation record")
    identity = PostReleaseClosureIdentity.from_pre_release(pre_release_record)
    normalized_at = utc(closed_at, "closed_at")
    checkpoint = pre_release_record.pre_release_checkpoint
    observation = pre_release_record.dispatch_observation
    if checkpoint is None or observation is None:
        raise ValueError("post-release closure lacks dispatch or pre-release evidence")
    if release_pending_fence.state is not TargetDispatchFenceState.RELEASE_PENDING:
        raise ValueError("initial post-release closure requires release-pending fence")
    if reservation_record.state not in {
        ReservationState.IN_FLIGHT,
        ReservationState.OUTCOME_UNKNOWN,
    }:
        raise ValueError("initial post-release closure requires unresolved reservation")
    if release_receipt.acquisition_receipt != reservation_record.identity.acquisition_receipt:
        raise ValueError("post-release release receipt changed acquisition")
    continuity_state = (
        PostReleaseContinuityState.CONTINUITY_UNPROVEN
        if force_quarantine
        else _initial_continuity_state(
            pre_release_record=pre_release_record,
            release_receipt=release_receipt,
        )
    )
    outcome = (
        PostReleaseClosureOutcome.RESOLVED
        if continuity_state is PostReleaseContinuityState.CONTINUITY
        else PostReleaseClosureOutcome.QUARANTINED
    )
    continuity_digest = _continuity_digest(
        pre_release_record=pre_release_record,
        release_receipt=release_receipt,
        reconciliation_evidence=None,
    )
    if outcome is PostReleaseClosureOutcome.RESOLVED:
        if observation.authoritative_status_digest is None:
            raise ValueError("resolved post-release closure requires authoritative sink status")
        next_reservation = complete_reservation(
            reservation_record,
            at=normalized_at,
            terminal_outcome_digest=continuity_digest,
            authoritative_status_digest=observation.authoritative_status_digest,
            irrevocable_non_acceptance=(
                observation.sink_state is AuthoritativeSinkState.NOT_ACCEPTED
            ),
        )
    elif reservation_record.state is ReservationState.OUTCOME_UNKNOWN:
        next_reservation = reservation_record
    else:
        next_reservation = quarantine_reservation(
            reservation_record,
            at=normalized_at,
            continuity_evidence_digest=continuity_digest,
        )
    next_fence = close_target_fence_after_release(
        release_pending_fence,
        quarantined=outcome is PostReleaseClosureOutcome.QUARANTINED,
        resolution_evidence_digest=_resolution_digest(
            continuity_evidence_digest=continuity_digest,
            reconciliation_evidence=None,
        ),
        changed_at=normalized_at,
    )
    record = create_post_release_closure_record(
        identity=identity,
        revision=1,
        prior_record_digest=None,
        phase=PostReleaseClosurePhase.INITIAL,
        outcome=outcome,
        pre_release_record=pre_release_record,
        prior_reservation=reservation_record,
        reservation=next_reservation,
        prior_fence=release_pending_fence,
        fence=next_fence,
        release_receipt=release_receipt,
        continuity_state=continuity_state,
        continuity_evidence_digest=continuity_digest,
        authoritative_status_digest=observation.authoritative_status_digest,
        reconciliation_evidence=None,
        closed_at=normalized_at,
    )
    return PostReleaseClosurePlan(
        pre_release_record=pre_release_record,
        prior_reservation_record=reservation_record,
        reservation_record=next_reservation,
        prior_fence_record=release_pending_fence,
        fence_record=next_fence,
        release_receipt=release_receipt,
        record=record,
    )


def build_reconciled_post_release_closure(
    *,
    prior_closure: PostReleaseClosureRecord,
    pre_release_record: SafeguardDispatchEvidenceRecord,
    reservation_record: IdempotencyReservationRecord,
    quarantined_fence: TargetDispatchFenceRecord,
    release_receipt: ResourceLockReleaseReceipt,
    evidence: PostReleaseReconciliationEvidence,
    reconciled_at: datetime,
) -> PostReleaseClosurePlan:
    """Resolve one quarantine from durable evidence without dispatching."""

    if (
        type(prior_closure) is not PostReleaseClosureRecord
        or prior_closure.outcome is not PostReleaseClosureOutcome.QUARANTINED
    ):
        raise ValueError("post-release reconciliation requires quarantined closure")
    if type(evidence) is not PostReleaseReconciliationEvidence:
        raise ValueError("post-release reconciliation requires exact durable evidence")
    identity = PostReleaseClosureIdentity.from_pre_release(pre_release_record)
    if identity != prior_closure.identity:
        raise ValueError("post-release reconciliation changed closure identity")
    if (
        pre_release_record.record_digest != prior_closure.pre_release_record_digest
        or pre_release_record.revision != prior_closure.pre_release_record_revision
    ):
        raise ValueError("post-release reconciliation changed pre-release evidence")
    if (
        release_receipt.receipt_digest != prior_closure.release_receipt_digest
        or release_receipt.state is not prior_closure.release_state
        or release_receipt.provider_attestation_digest != prior_closure.release_attestation_digest
        or release_receipt.observed_at != prior_closure.release_observed_at
        or release_receipt.recorded_at != prior_closure.release_recorded_at
    ):
        raise ValueError("post-release reconciliation rewrote release evidence")
    if (
        evidence.target_digest != identity.target_digest
        or evidence.target_fence_generation != identity.target_fence_generation
        or evidence.evidence_identity_digest != identity.evidence_identity_digest
    ):
        raise ValueError("post-release reconciliation evidence changed generation")
    if evidence.persisted_at < prior_closure.closed_at:
        raise ValueError("post-release reconciliation evidence predates quarantine")
    normalized_at = utc(reconciled_at, "reconciled_at")
    if normalized_at < evidence.persisted_at:
        raise ValueError("post-release reconciliation predates durable evidence")
    if reservation_record.record_digest != prior_closure.reservation_record_digest or (
        quarantined_fence.record_digest != prior_closure.fence_record_digest
    ):
        raise ValueError("post-release reconciliation predecessor changed")
    continuity_digest = _continuity_digest(
        pre_release_record=pre_release_record,
        release_receipt=release_receipt,
        reconciliation_evidence=evidence,
    )
    if evidence.kind is ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS:
        next_reservation = complete_reservation(
            reservation_record,
            at=normalized_at,
            terminal_outcome_digest=continuity_digest,
            authoritative_status_digest=evidence.evidence_digest,
            irrevocable_non_acceptance=(
                evidence.outcome is ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED
            ),
        )
        authoritative_status_digest: str | None = evidence.evidence_digest
    else:
        next_reservation = complete_reservation_from_verifier(
            reservation_record,
            at=normalized_at,
            terminal_outcome_digest=continuity_digest,
            independent_effect_receipt_digest=evidence.append_receipt_digest,
        )
        authoritative_status_digest = prior_closure.authoritative_status_digest
    next_fence = close_target_fence_after_release(
        quarantined_fence,
        quarantined=False,
        resolution_evidence_digest=_resolution_digest(
            continuity_evidence_digest=continuity_digest,
            reconciliation_evidence=evidence,
        ),
        changed_at=normalized_at,
    )
    record = create_post_release_closure_record(
        identity=identity,
        revision=prior_closure.revision + 1,
        prior_record_digest=prior_closure.record_digest,
        phase=PostReleaseClosurePhase.RECONCILIATION,
        outcome=PostReleaseClosureOutcome.RESOLVED,
        pre_release_record=pre_release_record,
        prior_reservation=reservation_record,
        reservation=next_reservation,
        prior_fence=quarantined_fence,
        fence=next_fence,
        release_receipt=release_receipt,
        continuity_state=prior_closure.continuity_state,
        continuity_evidence_digest=continuity_digest,
        authoritative_status_digest=authoritative_status_digest,
        reconciliation_evidence=evidence,
        closed_at=normalized_at,
    )
    return PostReleaseClosurePlan(
        pre_release_record=pre_release_record,
        prior_reservation_record=reservation_record,
        reservation_record=next_reservation,
        prior_fence_record=quarantined_fence,
        fence_record=next_fence,
        release_receipt=release_receipt,
        record=record,
    )


def _validate_plan_bindings(plan: PostReleaseClosurePlan) -> None:
    identity = plan.record.identity
    if PostReleaseClosureIdentity.from_pre_release(plan.pre_release_record) != identity:
        raise ValueError("post-release plan changed pre-release identity")
    start = plan.pre_release_record.dispatch_start_checkpoint
    if start is None:
        raise ValueError("post-release plan lacks dispatch-start lineage")
    if (
        plan.prior_reservation_record.identity.identity_digest
        != identity.reservation_identity_digest
        or plan.prior_reservation_record.identity.acquisition_receipt.attempt
        != identity.reservation_attempt
        or plan.release_receipt.acquisition_receipt
        != plan.prior_reservation_record.identity.acquisition_receipt
    ):
        raise ValueError("post-release plan changed reservation acquisition")
    if (
        plan.prior_fence_record.identity.target_digest != identity.target_digest
        or plan.prior_fence_record.identity.generation != identity.target_fence_generation
        or plan.prior_fence_record.identity.reservation_identity_digest
        != identity.reservation_identity_digest
    ):
        raise ValueError("post-release plan changed target fence generation")
    if plan.record.phase is PostReleaseClosurePhase.INITIAL:
        if plan.prior_fence_record.state is not TargetDispatchFenceState.RELEASE_PENDING:
            raise ValueError("initial post-release closure requires release-pending fence")
        validate_target_fence_transition(start.in_flight_fence, plan.prior_fence_record)
    elif plan.prior_fence_record.state is not TargetDispatchFenceState.QUARANTINED:
        raise ValueError("post-release reconciliation requires quarantined fence")
    if plan.reservation_record != plan.prior_reservation_record:
        validate_reservation_transition(
            plan.prior_reservation_record,
            plan.reservation_record,
        )
    validate_target_fence_transition(plan.prior_fence_record, plan.fence_record)
    expected = (
        plan.pre_release_record.record_digest,
        plan.prior_reservation_record.record_digest,
        plan.reservation_record.record_digest,
        plan.prior_fence_record.record_digest,
        plan.fence_record.record_digest,
        plan.release_receipt.receipt_digest,
    )
    actual = (
        plan.record.pre_release_record_digest,
        plan.record.prior_reservation_record_digest,
        plan.record.reservation_record_digest,
        plan.record.prior_fence_record_digest,
        plan.record.fence_record_digest,
        plan.record.release_receipt_digest,
    )
    if actual != expected:
        raise ValueError("post-release plan record digests mismatched exact records")
    if (
        plan.record.pre_release_record_revision != plan.pre_release_record.revision
        or plan.record.reservation_state is not plan.reservation_record.state
        or plan.record.reservation_revision != plan.reservation_record.revision
        or plan.record.fence_state is not plan.fence_record.state
        or plan.record.fence_revision != plan.fence_record.revision
        or plan.record.release_state is not plan.release_receipt.state
        or plan.record.release_attestation_digest
        != plan.release_receipt.provider_attestation_digest
        or plan.record.release_observed_at != plan.release_receipt.observed_at
        or plan.record.release_recorded_at != plan.release_receipt.recorded_at
    ):
        raise ValueError("post-release plan record fields mismatched exact records")


def _initial_continuity_state(
    *,
    pre_release_record: SafeguardDispatchEvidenceRecord,
    release_receipt: ResourceLockReleaseReceipt,
) -> PostReleaseContinuityState:
    checkpoint = pre_release_record.pre_release_checkpoint
    observation = pre_release_record.dispatch_observation
    if checkpoint is None or observation is None:
        raise ValueError("post-release continuity requires pre-release evidence")
    terminal_sink_state = observation.sink_state in {
        AuthoritativeSinkState.COMMITTED,
        AuthoritativeSinkState.NOT_COMMITTED,
        AuthoritativeSinkState.NOT_ACCEPTED,
    }
    return (
        PostReleaseContinuityState.CONTINUITY
        if checkpoint.continuity_state is PreReleaseContinuityState.CURRENT
        and release_receipt.state is ResourceLockReleaseState.RELEASED
        and terminal_sink_state
        else PostReleaseContinuityState.CONTINUITY_UNPROVEN
    )


def _continuity_digest(
    *,
    pre_release_record: SafeguardDispatchEvidenceRecord,
    release_receipt: ResourceLockReleaseReceipt,
    reconciliation_evidence: PostReleaseReconciliationEvidence | None,
) -> str:
    checkpoint = pre_release_record.pre_release_checkpoint
    observation = pre_release_record.dispatch_observation
    if checkpoint is None or observation is None:
        raise ValueError("post-release continuity digest lacks evidence")
    return content_digest(
        {
            "domain": "post-release-continuity-evidence",
            "pre_release_record_digest": pre_release_record.record_digest,
            "checkpoint_digest": checkpoint.checkpoint_digest,
            "observation_digest": observation.observation_digest,
            "release_receipt_digest": release_receipt.receipt_digest,
            "reconciliation_append_receipt_digest": (
                reconciliation_evidence.append_receipt_digest
                if reconciliation_evidence is not None
                else None
            ),
        }
    )


def _resolution_digest(
    *,
    continuity_evidence_digest: str,
    reconciliation_evidence: PostReleaseReconciliationEvidence | None,
) -> str:
    return content_digest(
        {
            "domain": "post-release-target-resolution",
            "continuity_evidence_digest": continuity_evidence_digest,
            "reconciliation_evidence_digest": (
                reconciliation_evidence.evidence_digest
                if reconciliation_evidence is not None
                else None
            ),
            "reconciliation_append_receipt_digest": (
                reconciliation_evidence.append_receipt_digest
                if reconciliation_evidence is not None
                else None
            ),
        }
    )


__all__ = [
    "PostReleaseClosurePlan",
    "build_initial_post_release_closure",
    "build_reconciled_post_release_closure",
]
