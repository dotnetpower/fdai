"""Atomic post-release closure and reconciliation contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    ReservationEvidenceKind,
    ReservationState,
    reopen_reservation,
)
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    PostReleaseContinuityState,
    PostReleaseReconciliationEvidence,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
    audit_closure_mapping,
    closure_outbox_mapping,
)
from fdai.core.executor.post_release_closure_codec import (
    post_release_closure_from_mapping,
    post_release_closure_to_mapping,
)
from fdai.core.executor.post_release_closure_plan import (
    PostReleaseClosurePlan,
    build_initial_post_release_closure,
    build_reconciled_post_release_closure,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    ContinuityUnprovenReason,
    DispatchTransportState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchObservation,
    record_dispatch_observation,
    record_pre_release_checkpoint,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    mark_target_fence_release_pending,
)
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)

from tests.core.executor.test_safeguard_dispatch_checkpoint import (
    _DIGEST,
    _NOW,
    _assessment,
    _dispatch_started_record,
    _evidence_fixture,
)
from tests.core.executor.test_target_dispatch_fence import _policy


def _pre_release(
    *,
    sink_state: AuthoritativeSinkState,
    continuity_proven: bool = True,
    action_name: str = "example",
    idempotency_key: str = "example-idem",
    target_resource_ref: str = "resource/example",
    now: datetime = _NOW,
) -> tuple[
    SafeguardDispatchEvidenceRecord,
    TargetDispatchFenceRecord,
]:
    bundle, reservation, _preparing, prepared, context = _evidence_fixture(
        action_name=action_name,
        idempotency_key=idempotency_key,
        target_ref=target_resource_ref,
        now=now,
    )
    started, _persistence = _dispatch_started_record(
        bundle,
        prepared_fence=prepared,
        context=context,
        at=now,
    )
    known = sink_state in {
        AuthoritativeSinkState.ACCEPTED,
        AuthoritativeSinkState.NOT_ACCEPTED,
        AuthoritativeSinkState.COMMITTED,
        AuthoritativeSinkState.NOT_COMMITTED,
    }
    accepted = sink_state in {
        AuthoritativeSinkState.ACCEPTED,
        AuthoritativeSinkState.COMMITTED,
    }
    observation = SafeguardDispatchObservation.create(
        dispatch_start_record=started,
        transport_state=DispatchTransportState.ACKNOWLEDGED,
        sink_state=sink_state,
        sink_operation_reference_digest=_DIGEST if accepted else None,
        authoritative_status_digest=_DIGEST if known else None,
        observed_at=now + timedelta(seconds=1),
    )
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    if continuity_proven:
        assessment = _assessment(reservation, now=now)
        checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
            evidence_identity=observed.identity,
            assessment=assessment,
            not_before=observation.observed_at,
            observed_at=now + timedelta(seconds=2),
        )
        pre_release = record_pre_release_checkpoint(
            observed,
            checkpoint=checkpoint,
            current_lock_assessment=assessment,
            changed_at=checkpoint.observed_at,
        )
    else:
        checkpoint = PreReleaseOwnershipCheckpoint.unproven(
            evidence_identity=observed.identity,
            reason=ContinuityUnprovenReason.CALLBACK_CANCELLED,
            observed_at=now + timedelta(seconds=2),
        )
        pre_release = record_pre_release_checkpoint(
            observed,
            checkpoint=checkpoint,
            changed_at=checkpoint.observed_at,
        )
    start = pre_release.dispatch_start_checkpoint
    assert start is not None
    return (
        pre_release,
        mark_target_fence_release_pending(
            start.in_flight_fence,
            changed_at=now + timedelta(seconds=2),
        ),
    )


def _release_receipt(
    record: SafeguardDispatchEvidenceRecord,
    *,
    state: ResourceLockReleaseState = ResourceLockReleaseState.RELEASED,
    attestation: str = "sha256:" + "c" * 64,
    now: datetime = _NOW,
) -> ResourceLockReleaseReceipt:
    start = record.dispatch_start_checkpoint
    assert start is not None
    acquisition = start.in_flight_reservation_receipt.record.identity.acquisition_receipt
    return ResourceLockReleaseReceipt.create(
        acquisition_receipt=acquisition,
        state=state,
        provider_attestation_digest=attestation,
        observed_at=(
            now + timedelta(seconds=3) if state is not ResourceLockReleaseState.UNKNOWN else None
        ),
        recorded_at=now + timedelta(seconds=3),
    )


def _initial_plan(
    *,
    sink_state: AuthoritativeSinkState,
    continuity_proven: bool = True,
    release_state: ResourceLockReleaseState = ResourceLockReleaseState.RELEASED,
    action_name: str = "example",
    idempotency_key: str = "example-idem",
    target_resource_ref: str = "resource/example",
    now: datetime = _NOW,
) -> PostReleaseClosurePlan:
    pre_release, release_pending = _pre_release(
        sink_state=sink_state,
        continuity_proven=continuity_proven,
        action_name=action_name,
        idempotency_key=idempotency_key,
        target_resource_ref=target_resource_ref,
        now=now,
    )
    start = pre_release.dispatch_start_checkpoint
    assert start is not None
    return build_initial_post_release_closure(
        pre_release_record=pre_release,
        reservation_record=start.in_flight_reservation_receipt.record,
        release_pending_fence=release_pending,
        release_receipt=_release_receipt(
            pre_release,
            state=release_state,
            now=now,
        ),
        closed_at=now + timedelta(seconds=4),
    )


def _reconciliation_evidence(
    plan: PostReleaseClosurePlan,
    *,
    kind: ReconciliationEvidenceKind,
    outcome: ReconciliationOutcome,
    now: datetime = _NOW,
) -> PostReleaseReconciliationEvidence:
    return PostReleaseReconciliationEvidence.create(
        kind=kind,
        outcome=outcome,
        target_digest=plan.record.identity.target_digest,
        target_fence_generation=plan.record.identity.target_fence_generation,
        evidence_identity_digest=plan.record.identity.evidence_identity_digest,
        source_id=(
            "authoritative-sink-status"
            if kind is ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS
            else "independent-effect-verifier"
        ),
        source_version="1.0.0",
        trust_anchor_id="example:primary",
        evidence_digest="sha256:" + "d" * 64,
        observed_at=now + timedelta(seconds=5),
        persisted_at=now + timedelta(seconds=5),
        append_receipt_digest="sha256:" + "e" * 64,
    )


def test_released_committed_dispatch_resolves_all_terminal_axes() -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)

    assert plan.record.outcome is PostReleaseClosureOutcome.RESOLVED
    assert plan.record.continuity_state is PostReleaseContinuityState.CONTINUITY
    assert plan.reservation_record.state is ReservationState.TERMINAL
    assert plan.reservation_record.evidence_kind is ReservationEvidenceKind.SINK_TERMINAL_OUTCOME
    assert plan.fence_record.state.value == "resolved"
    assert plan.record.independent_effect_state == "pending"
    assert plan.record.effect_verified is False
    assert (
        post_release_closure_from_mapping(post_release_closure_to_mapping(plan.record))
        == plan.record
    )


@pytest.mark.parametrize(
    ("sink_state", "continuity_proven", "release_state"),
    [
        (AuthoritativeSinkState.ACCEPTED, True, ResourceLockReleaseState.RELEASED),
        (AuthoritativeSinkState.COMMITTED, False, ResourceLockReleaseState.RELEASED),
        (AuthoritativeSinkState.COMMITTED, True, ResourceLockReleaseState.UNKNOWN),
        (AuthoritativeSinkState.UNKNOWN, True, ResourceLockReleaseState.RELEASED),
    ],
)
def test_ambiguous_or_unproven_closure_quarantines_target_and_reservation(
    sink_state: AuthoritativeSinkState,
    continuity_proven: bool,
    release_state: ResourceLockReleaseState,
) -> None:
    plan = _initial_plan(
        sink_state=sink_state,
        continuity_proven=continuity_proven,
        release_state=release_state,
    )

    assert plan.record.outcome is PostReleaseClosureOutcome.QUARANTINED
    assert plan.record.continuity_state is PostReleaseContinuityState.CONTINUITY_UNPROVEN
    assert plan.reservation_record.state is ReservationState.OUTCOME_UNKNOWN
    assert plan.reservation_record.evidence_kind is ReservationEvidenceKind.CONTINUITY_UNPROVEN
    assert plan.fence_record.state.value == "quarantined"


def test_closure_identity_does_not_depend_on_release_receipt() -> None:
    pre_release, release_pending = _pre_release(
        sink_state=AuthoritativeSinkState.COMMITTED,
    )
    start = pre_release.dispatch_start_checkpoint
    assert start is not None
    first = build_initial_post_release_closure(
        pre_release_record=pre_release,
        reservation_record=start.in_flight_reservation_receipt.record,
        release_pending_fence=release_pending,
        release_receipt=_release_receipt(
            pre_release,
            attestation="sha256:" + "1" * 64,
        ),
        closed_at=_NOW + timedelta(seconds=4),
    )
    second = build_initial_post_release_closure(
        pre_release_record=pre_release,
        reservation_record=start.in_flight_reservation_receipt.record,
        release_pending_fence=release_pending,
        release_receipt=_release_receipt(
            pre_release,
            state=ResourceLockReleaseState.UNKNOWN,
            attestation="sha256:" + "2" * 64,
        ),
        closed_at=_NOW + timedelta(seconds=4),
    )

    assert first.record.identity == second.record.identity
    assert first.record.release_receipt_digest != second.record.release_receipt_digest


def test_initial_closure_requires_exact_release_pending_fence() -> None:
    pre_release, _release_pending = _pre_release(
        sink_state=AuthoritativeSinkState.COMMITTED,
    )
    start = pre_release.dispatch_start_checkpoint
    assert start is not None

    with pytest.raises(ValueError, match="release-pending"):
        build_initial_post_release_closure(
            pre_release_record=pre_release,
            reservation_record=start.in_flight_reservation_receipt.record,
            release_pending_fence=start.in_flight_fence,
            release_receipt=_release_receipt(pre_release),
            closed_at=_NOW + timedelta(seconds=4),
        )


def test_authoritative_non_acceptance_reconciliation_allows_later_recovery() -> None:
    initial = _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)
    evidence = _reconciliation_evidence(
        initial,
        kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
        outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
    )

    reconciled = build_reconciled_post_release_closure(
        prior_closure=initial.record,
        pre_release_record=initial.pre_release_record,
        reservation_record=initial.reservation_record,
        quarantined_fence=initial.fence_record,
        release_receipt=initial.release_receipt,
        evidence=evidence,
        reconciled_at=_NOW + timedelta(seconds=6),
    )

    assert reconciled.record.outcome is PostReleaseClosureOutcome.RESOLVED
    assert reconciled.record.revision == 2
    assert reconciled.record.prior_record_digest == initial.record.record_digest
    assert (
        reconciled.reservation_record.evidence_kind
        is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
    )
    assert reconciled.fence_record.state.value == "resolved"


def test_higher_attempt_requires_later_acquisition_and_resolved_generation() -> None:
    initial = _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)
    evidence = _reconciliation_evidence(
        initial,
        kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
        outcome=ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
    )
    reconciled = build_reconciled_post_release_closure(
        prior_closure=initial.record,
        pre_release_record=initial.pre_release_record,
        reservation_record=initial.reservation_record,
        quarantined_fence=initial.fence_record,
        release_receipt=initial.release_receipt,
        evidence=evidence,
        reconciled_at=_NOW + timedelta(seconds=6),
    )
    prior_identity = reconciled.reservation_record.identity
    prior_acquisition = prior_identity.acquisition_receipt
    request = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest=prior_identity.action_digest,
        attempt=prior_acquisition.attempt + 1,
        producer_id=prior_acquisition.producer_id,
        producer_version=prior_acquisition.producer_version,
        source_revision=prior_identity.source_revision,
    )
    acquisition = ResourceLockAcquisitionReceipt.create(
        lock_key=request.lock_key,
        target_digest=request.target_digest,
        action_digest=request.action_digest,
        attempt=request.attempt,
        provider_id=prior_acquisition.provider_id,
        provider_version=prior_acquisition.provider_version,
        producer_id=request.producer_id,
        producer_version=request.producer_version,
        owner_token_digest="sha256:" + "7" * 64,
        fencing_generation=None,
        session_identity="session:2",
        provider_attestation_digest="sha256:" + "8" * 64,
        trust_anchor_id=prior_acquisition.trust_anchor_id,
        acquired_at=_NOW + timedelta(seconds=7),
        valid_until=None,
        source_revision=request.source_revision,
        request_digest=request.request_digest,
    )
    candidate_identity = IdempotencyReservationIdentity.create(
        idempotency_key=prior_identity.idempotency_key,
        action_digest=prior_identity.action_digest,
        execution_path=prior_identity.execution_path,
        execution_fingerprint=prior_identity.execution_fingerprint,
        source_revision=prior_identity.source_revision,
        acquisition_receipt=acquisition,
    )
    reopened = reopen_reservation(
        reconciled.reservation_record,
        candidate_identity=candidate_identity,
        reserved_at=_NOW + timedelta(seconds=7),
        lease_expires_at=_NOW + timedelta(seconds=37),
    )
    next_fence_identity = TargetDispatchFenceIdentity.create(
        target_digest=acquisition.target_digest,
        reservation_identity=candidate_identity,
        continuity_policy=_policy(),
        generation=reconciled.fence_record.identity.generation + 1,
        client_correlation_id="correlation:attempt-2",
        sink_idempotency_key="sink:attempt-2",
    )
    preparing = TargetDispatchFenceRecord.create_preparing(
        identity=next_fence_identity,
        changed_at=_NOW + timedelta(seconds=7),
        prior_resolved_record=reconciled.fence_record,
    )

    assert reopened.state is ReservationState.RESERVED
    assert reopened.identity.acquisition_receipt.attempt == 2
    assert preparing.state.value == "preparing"
    assert preparing.identity.generation == 2
    assert preparing.prior_record_digest == reconciled.fence_record.record_digest


def test_independent_verifier_reconciliation_stays_separate_from_closure_authority() -> None:
    initial = _initial_plan(
        sink_state=AuthoritativeSinkState.UNKNOWN,
        release_state=ResourceLockReleaseState.UNKNOWN,
    )
    evidence = _reconciliation_evidence(
        initial,
        kind=ReconciliationEvidenceKind.INDEPENDENT_EFFECT,
        outcome=ReconciliationOutcome.EFFECT_VERIFIED,
    )

    reconciled = build_reconciled_post_release_closure(
        prior_closure=initial.record,
        pre_release_record=initial.pre_release_record,
        reservation_record=initial.reservation_record,
        quarantined_fence=initial.fence_record,
        release_receipt=initial.release_receipt,
        evidence=evidence,
        reconciled_at=_NOW + timedelta(seconds=6),
    )

    assert (
        reconciled.reservation_record.evidence_kind
        is ReservationEvidenceKind.INDEPENDENT_EFFECT_OUTCOME
    )
    assert reconciled.record.independent_effect_state == "pending"
    assert reconciled.record.effect_verified is False
    assert reconciled.record.reconciliation_evidence == evidence


def test_reconciliation_rejects_generation_substitution() -> None:
    initial = _initial_plan(sink_state=AuthoritativeSinkState.ACCEPTED)
    evidence = replace(
        _reconciliation_evidence(
            initial,
            kind=ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS,
            outcome=ReconciliationOutcome.SINK_COMMITTED,
        ),
        target_fence_generation=2,
    )

    with pytest.raises(ValueError, match="changed generation"):
        build_reconciled_post_release_closure(
            prior_closure=initial.record,
            pre_release_record=initial.pre_release_record,
            reservation_record=initial.reservation_record,
            quarantined_fence=initial.fence_record,
            release_receipt=initial.release_receipt,
            evidence=evidence,
            reconciled_at=_NOW + timedelta(seconds=6),
        )


def test_audit_and_outbox_bind_exact_closure_revision() -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)

    audit = audit_closure_mapping(plan.record)
    outbox = closure_outbox_mapping(plan.record)

    assert audit["audit_closure_digest"] == plan.record.audit_closure_digest
    assert audit["pre_effect_audit_append_receipt_digest"] == (
        plan.record.identity.audit_append_receipt_digest
    )
    assert outbox["event_id"] == plan.record.outbox_event_id
    assert outbox["closure_record_digest"] == plan.record.record_digest
    assert outbox["effect_verified"] is False


def test_codec_rejects_extra_fields() -> None:
    plan = _initial_plan(sink_state=AuthoritativeSinkState.COMMITTED)
    mapping = post_release_closure_to_mapping(plan.record)
    mapping["unexpected"] = True

    with pytest.raises(ValueError, match="fields are invalid"):
        post_release_closure_from_mapping(mapping)
