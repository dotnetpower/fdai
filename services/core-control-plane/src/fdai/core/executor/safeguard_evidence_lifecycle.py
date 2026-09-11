"""Provider-neutral safeguard evidence lifecycle orchestrator.

Enforces exact phase ordering, one passed-down lock handle, fail-closed
evidence validation, dispatch/commit/effect/release separation, quarantine,
restart/duplicate/cancellation/contention behavior, and returns the finalized
bundle digest and terminal evidence without granting authority.

Phase order (every invocation MUST execute in this sequence):

1. Acquire evidenced target lock          (caller-owned context manager)
2. Reserve / reconcile idempotency        (caller supplies receipt)
3. Persist / read-back audit intent       (caller supplies receipt)
4. Acquire target fence generation        (caller supplies preparing fence)
5. Finalize no-authority safeguard bundle (caller supplies evidence record)
6. Persist bundle evidence & prepare fence
7. Begin in-flight state (fence + reservation)
8. Dispatch while the same handle remains active
9. Record continuity and terminal/outbox state
10. Return pre-release result; caller releases lock via context exit

Implements: #681 exit criteria.
Primitives:  #692 target dispatch fences, #693 dispatch checkpoints,
             #694 post-release closure (store seam only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from fdai.core.executor.audit_intent import AuditIntentAppendReceipt
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationStore,
    IdempotencyReservationTransitionReceipt,
    ReservationState,
)
from fdai.core.executor.idempotency_reservation import (
    begin_dispatch as _begin_reservation_dispatch,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    PreReleaseContinuityState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
    SafeguardDispatchObservation,
    record_dispatch_observation,
    record_dispatch_start,
    record_pre_release_checkpoint,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchEvidenceStore,
    SafeguardDispatchPersistenceDecision,
    SafeguardDispatchTransitionReceipt,
)
from fdai.core.executor.safeguard_dispatch_support import (
    utc,
    validate_digest,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    attach_prepared_evidence,
    mark_target_fence_in_flight,
    mark_target_fence_release_pending,
    resolve_target_fence_without_dispatch,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceStore,
)
from fdai.shared.providers.resource_lock import (
    HeldResourceLock,
    LiveLockOwnershipAssessment,
)

# ---------------------------------------------------------------------------
# Terminal outcome
# ---------------------------------------------------------------------------


class LifecycleTerminalKind(StrEnum):
    """Provider-neutral terminal disposition without authority."""

    RESOLVED = "resolved"
    QUARANTINED = "quarantined"
    FENCE_BLOCKED = "fence_blocked"
    FENCE_DUPLICATE = "fence_duplicate"
    EVIDENCE_CONFLICT = "evidence_conflict"
    CANCELLED_BEFORE_DISPATCH = "cancelled_before_dispatch"


@dataclass(frozen=True, slots=True)
class SafeguardEvidenceLifecycleResult:
    """Terminal outcome returned to the orchestrator's caller.

    Contains the finalized bundle digest and terminal evidence without
    granting approval, execution, promotion, sink-commit, or effect-
    verification authority.  Lock release is the caller's responsibility
    (context-manager exit).
    """

    kind: LifecycleTerminalKind
    bundle_digest: str | None
    fence_record: TargetDispatchFenceRecord | None
    evidence_record: SafeguardDispatchEvidenceRecord | None
    pre_release_receipt: SafeguardDispatchTransitionReceipt | None
    release_pending_fence: TargetDispatchFenceRecord | None
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("safeguard evidence lifecycle result MUST NOT grant authority")
        if type(self.kind) is not LifecycleTerminalKind:
            raise ValueError("safeguard evidence lifecycle result kind is invalid")
        if self.bundle_digest is not None:
            validate_digest("bundle_digest", self.bundle_digest)
        _validate_terminal_shape(self)


# ---------------------------------------------------------------------------
# Dispatch port (provider-neutral call-the-sink seam)
# ---------------------------------------------------------------------------


@runtime_checkable
class DispatchPort(Protocol):
    """Provider-neutral seam that calls the external effect sink.

    The orchestrator calls this exactly once while the target lock is held.
    Implementations MUST NOT grant execution authority, perform sink commit,
    or claim independent effect verification.
    """

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        """Call the sink and return transport, sink, op-ref, status digests."""
        ...


# ---------------------------------------------------------------------------
# Lifecycle orchestrator
# ---------------------------------------------------------------------------


async def run_safeguard_evidence_lifecycle(
    *,
    held_lock: HeldResourceLock,
    reservation_receipt: IdempotencyReservationTransitionReceipt,
    audit_append_receipt: AuditIntentAppendReceipt,
    bundle_record: SafeguardDispatchEvidenceRecord,
    preparing_fence: TargetDispatchFenceRecord,
    reservation_store: IdempotencyReservationStore,
    fence_store: TargetDispatchFenceStore,
    evidence_store: SafeguardDispatchEvidenceStore,
    dispatch_port: DispatchPort,
    now: datetime,
) -> SafeguardEvidenceLifecycleResult:
    """Execute the in-lock safeguard evidence lifecycle in exact phase order.

    The caller MUST have already completed phases 1-5 and supplies their
    receipts.  This function continues from phase 6 (persist bundle
    evidence) through phase 9 (pre-release checkpoint).  Lock release is
    the caller's responsibility via context-manager exit.

    Returns a terminal result carrying the finalized bundle digest and
    terminal evidence **without authority**.
    """

    current_time = utc(now, "now")

    # -- Prior-phase validation -------------------------------------------
    _validate_prior_phases(
        held_lock=held_lock,
        reservation_receipt=reservation_receipt,
        audit_append_receipt=audit_append_receipt,
        bundle_record=bundle_record,
        preparing_fence=preparing_fence,
    )

    # -- Phase 6: persist bundle evidence ---------------------------------
    persist_result = await evidence_store.persist_bundle(bundle_record)

    if persist_result.decision is SafeguardDispatchPersistenceDecision.CONFLICT:
        return _early_exit(
            LifecycleTerminalKind.EVIDENCE_CONFLICT,
            bundle_record,
            preparing_fence,
            persist_result.observed_record,
        )

    if persist_result.decision is SafeguardDispatchPersistenceDecision.DUPLICATE_SAME:
        return _early_exit(
            LifecycleTerminalKind.EVIDENCE_CONFLICT,
            bundle_record,
            preparing_fence,
            persist_result.observed_record,
        )

    bundle_persistence_receipt = persist_result.transition_receipt
    if bundle_persistence_receipt is None:
        raise ValueError("store contract violated: persisted bundle lacks receipt")

    # -- Phase 6b: CAS fence -> prepared ----------------------------------
    prepared_fence = attach_prepared_evidence(
        preparing_fence,
        audit_append_receipt=audit_append_receipt,
        safeguard_bundle_digest=bundle_record.bundle.bundle_digest,
        changed_at=current_time,
    )
    await fence_store.compare_and_transition(
        prior_record_digest=preparing_fence.record_digest,
        expected_revision=preparing_fence.revision,
        record=prepared_fence,
    )

    # -- Phase 7: begin in-flight state -----------------------------------
    # 7a: fence -> in_flight
    in_flight_fence = mark_target_fence_in_flight(
        prepared_fence,
        changed_at=current_time,
    )
    await fence_store.compare_and_transition(
        prior_record_digest=prepared_fence.record_digest,
        expected_revision=prepared_fence.revision,
        record=in_flight_fence,
    )

    # 7b: reservation -> in_flight
    in_flight_reservation = _begin_reservation_dispatch(
        reservation_receipt.record,
        at=current_time,
    )
    in_flight_reservation_receipt = await reservation_store.compare_and_transition(
        prior_record_digest=reservation_receipt.record.record_digest,
        expected_prior_revision=reservation_receipt.record.revision,
        record=in_flight_reservation,
    )

    # 7c: evidence -> dispatch_started
    dispatch_started = record_dispatch_start(
        bundle_record,
        bundle_persistence_receipt=bundle_persistence_receipt,
        in_flight_reservation_receipt=in_flight_reservation_receipt,
        prepared_fence=prepared_fence,
        in_flight_fence=in_flight_fence,
        dispatch_started_at=current_time,
        changed_at=current_time,
    )
    await evidence_store.compare_and_transition(
        prior_record_digest=bundle_record.record_digest,
        expected_revision=bundle_record.revision,
        record=dispatch_started,
        bundle_persistence_receipt=bundle_persistence_receipt,
    )

    # -- Phase 8: dispatch (same lock handle active) ----------------------
    held_lock.require_active()

    transport_state, sink_state, op_ref_digest, status_digest = await dispatch_port.dispatch(
        evidence_record=dispatch_started,
        started_at=current_time,
    )

    # 8a: record observation
    observation = SafeguardDispatchObservation.create(
        dispatch_start_record=dispatch_started,
        transport_state=transport_state,
        sink_state=sink_state,
        sink_operation_reference_digest=op_ref_digest,
        authoritative_status_digest=status_digest,
        observed_at=current_time,
    )
    observed = record_dispatch_observation(
        dispatch_started,
        observation=observation,
        changed_at=current_time,
    )
    await evidence_store.compare_and_transition(
        prior_record_digest=dispatch_started.record_digest,
        expected_revision=dispatch_started.revision,
        record=observed,
    )

    # -- Phase 9: record continuity and pre-release -----------------------
    # 9a: fresh ownership assessment
    assessment = await held_lock.assess_ownership()
    # The pre-release state_changed_at must be >= assessment.evaluated_at
    # per require_current_lock_ownership; use the later timestamp.
    pre_release_time = max(current_time, assessment.evaluated_at)
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=bundle_record.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=pre_release_time,
    )
    # Pass assessment only when continuity is current; unproven edges
    # reject a non-None assessment per the transition validator.
    assessment_for_transition: LiveLockOwnershipAssessment | None = (
        assessment if checkpoint.continuity_state is PreReleaseContinuityState.CURRENT else None
    )
    pre_release = record_pre_release_checkpoint(
        observed,
        checkpoint=checkpoint,
        current_lock_assessment=assessment_for_transition,
        changed_at=pre_release_time,
    )
    pre_release_receipt = await evidence_store.compare_and_transition(
        prior_record_digest=observed.record_digest,
        expected_revision=observed.revision,
        record=pre_release,
        current_lock_assessment=assessment_for_transition,
    )

    # 9b: fence -> release_pending (before lock context exits)
    release_pending_fence = mark_target_fence_release_pending(
        in_flight_fence,
        changed_at=pre_release_time,
    )
    await fence_store.compare_and_transition(
        prior_record_digest=in_flight_fence.record_digest,
        expected_revision=in_flight_fence.revision,
        record=release_pending_fence,
    )

    # Determine terminal disposition from pre-release evidence
    quarantined = (
        checkpoint.continuity_state is PreReleaseContinuityState.CONTINUITY_UNPROVEN
        or sink_state
        in {
            AuthoritativeSinkState.UNOBSERVED,
            AuthoritativeSinkState.UNKNOWN,
        }
        or transport_state in {DispatchTransportState.FAILED, DispatchTransportState.UNKNOWN}
    )
    terminal_kind = (
        LifecycleTerminalKind.QUARANTINED if quarantined else LifecycleTerminalKind.RESOLVED
    )

    return SafeguardEvidenceLifecycleResult(
        kind=terminal_kind,
        bundle_digest=bundle_record.bundle.bundle_digest,
        fence_record=release_pending_fence,
        evidence_record=pre_release,
        pre_release_receipt=pre_release_receipt,
        release_pending_fence=release_pending_fence,
    )


async def cancel_before_dispatch(
    *,
    held_lock: HeldResourceLock,
    preparing_fence: TargetDispatchFenceRecord,
    no_dispatch_evidence_digest: str,
    fence_store: TargetDispatchFenceStore,
    now: datetime,
) -> SafeguardEvidenceLifecycleResult:
    """Cancel a lifecycle that has not yet dispatched.

    Resolves the target fence with no-dispatch evidence.  Lock release
    remains the caller's responsibility (context-manager exit).
    """

    current_time = utc(now, "now")
    held_lock.require_active()
    resolved = resolve_target_fence_without_dispatch(
        preparing_fence,
        no_dispatch_evidence_digest=no_dispatch_evidence_digest,
        changed_at=current_time,
    )
    await fence_store.compare_and_transition(
        prior_record_digest=preparing_fence.record_digest,
        expected_revision=preparing_fence.revision,
        record=resolved,
    )

    return SafeguardEvidenceLifecycleResult(
        kind=LifecycleTerminalKind.CANCELLED_BEFORE_DISPATCH,
        bundle_digest=None,
        fence_record=resolved,
        evidence_record=None,
        pre_release_receipt=None,
        release_pending_fence=None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _early_exit(
    kind: LifecycleTerminalKind,
    bundle_record: SafeguardDispatchEvidenceRecord,
    fence_record: TargetDispatchFenceRecord,
    observed: SafeguardDispatchEvidenceRecord,
) -> SafeguardEvidenceLifecycleResult:
    """Build a terminal result for evidence conflicts without dispatch."""

    return SafeguardEvidenceLifecycleResult(
        kind=kind,
        bundle_digest=bundle_record.bundle.bundle_digest,
        fence_record=fence_record,
        evidence_record=observed,
        pre_release_receipt=None,
        release_pending_fence=None,
    )


def _validate_prior_phases(
    *,
    held_lock: HeldResourceLock,
    reservation_receipt: IdempotencyReservationTransitionReceipt,
    audit_append_receipt: AuditIntentAppendReceipt,
    bundle_record: SafeguardDispatchEvidenceRecord,
    preparing_fence: TargetDispatchFenceRecord,
) -> None:
    """Fail closed if any prior-phase evidence is inconsistent."""

    # Lock must be held
    held_lock.require_active()

    # Reservation must be current-reserved
    if reservation_receipt.record.state is not ReservationState.RESERVED:
        raise ValueError("lifecycle requires a current reserved idempotency state")

    # Audit must bind to this reservation
    if (
        audit_append_receipt.intent.reservation_receipt.record.identity.identity_digest
        != reservation_receipt.record.identity.identity_digest
    ):
        raise ValueError("lifecycle audit intent changed reservation identity")

    # Bundle must be in bundle_persisted state
    if bundle_record.state is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED:
        raise ValueError("lifecycle requires bundle-persisted evidence state")

    # Fence must be in preparing state
    if preparing_fence.state is not TargetDispatchFenceState.PREPARING:
        raise ValueError("lifecycle requires a preparing target fence")

    # Fence identity must bind to reservation
    if (
        preparing_fence.identity.reservation_identity_digest
        != reservation_receipt.record.identity.identity_digest
    ):
        raise ValueError("lifecycle fence changed reservation identity")

    # Bundle must carry no authority
    if bundle_record.execution_authority is not False or bundle_record.effect_verified is not False:
        raise ValueError("lifecycle bundle MUST NOT grant authority")


def _validate_terminal_shape(result: SafeguardEvidenceLifecycleResult) -> None:
    """Enforce invariants on each terminal kind."""

    kind = result.kind

    if kind in {LifecycleTerminalKind.RESOLVED, LifecycleTerminalKind.QUARANTINED}:
        if result.bundle_digest is None:
            raise ValueError("completed lifecycle requires bundle digest")
        if result.fence_record is None or result.evidence_record is None:
            raise ValueError("completed lifecycle requires terminal records")
        if result.pre_release_receipt is None:
            raise ValueError("completed lifecycle requires pre-release receipt")
        if result.release_pending_fence is None:
            raise ValueError("completed lifecycle requires release-pending fence")

    if kind is LifecycleTerminalKind.CANCELLED_BEFORE_DISPATCH:
        if result.bundle_digest is not None:
            raise ValueError("cancelled lifecycle MUST NOT have bundle digest")
        if result.fence_record is None:
            raise ValueError("cancelled lifecycle requires resolved fence")

    if kind in {
        LifecycleTerminalKind.FENCE_BLOCKED,
        LifecycleTerminalKind.FENCE_DUPLICATE,
        LifecycleTerminalKind.EVIDENCE_CONFLICT,
    }:
        if result.pre_release_receipt is not None:
            raise ValueError("early-exit lifecycle MUST NOT have pre-release receipt")
        if result.release_pending_fence is not None:
            raise ValueError("early-exit lifecycle MUST NOT have release-pending fence")


__all__ = [
    "DispatchPort",
    "LifecycleTerminalKind",
    "SafeguardEvidenceLifecycleResult",
    "cancel_before_dispatch",
    "run_safeguard_evidence_lifecycle",
]
