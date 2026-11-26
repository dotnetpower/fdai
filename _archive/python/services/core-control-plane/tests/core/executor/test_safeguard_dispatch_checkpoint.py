"""Safeguard dispatch and pre-release checkpoint contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from fdai.core.executor import target_dispatch_fence as fence_model
from fdai.core.executor.audit_intent import (
    AuditIntentAppendReceipt,
    PreEffectAuditIntent,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationTransitionReceipt,
    begin_dispatch,
)
from fdai.core.executor.safeguard_bundle_context import (
    SafeguardBundlePersistenceContext,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    ContinuityUnprovenReason,
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
from fdai.core.executor.safeguard_dispatch_codec import (
    safeguard_dispatch_record_from_mapping,
    safeguard_dispatch_record_to_mapping,
)
from fdai.core.executor.safeguard_dispatch_gate import validate_dispatch_start
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchTransitionReceipt,
)
from fdai.core.executor.safeguard_dispatch_transition import (
    validate_dispatch_evidence_transition,
)
from fdai.core.executor.safeguard_pre_bundle import SafeguardPreBundleCommitment
from fdai.core.executor.safeguard_proofs import (
    AuditIntentProof,
    IdempotencyReservationProof,
    LogicalTargetLockProof,
    finalize_safeguard_proof_bundle,
    full_action_digest,
)
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    attach_prepared_evidence,
    mark_target_fence_in_flight,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)
from fdai_service_contracts.execution_safeguards import (
    SafeguardProof,
    SafeguardProofBundle,
    SafeguardProofKind,
)

from tests.core.executor.test_safeguard_proofs import (
    _action,
)
from tests.core.executor.test_target_dispatch_fence import (
    _NOW,
    _policy,
)

_DIGEST = "sha256:" + "a" * 64
_SOURCE_REVISION = "commit:" + "b" * 40


def _evidence_fixture(
    *,
    action_name: str = "example",
    idempotency_key: str = "example-idem",
    attempt: int = 1,
    now: datetime = _NOW,
    target_ref: str = "resource/example",
) -> tuple[
    SafeguardDispatchEvidenceRecord,
    IdempotencyReservationIdentity,
    TargetDispatchFenceRecord,
    TargetDispatchFenceRecord,
    SafeguardBundlePersistenceContext,
]:
    action = _action(
        created_at=now,
        idempotency_key=idempotency_key,
        params={"name": action_name},
        target_resource_ref=target_ref,
    )
    safeguard_receipt = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.DIRECT_API,
        plan_digest="plan-digest",
        plan_kind="test-plan",
    )
    assert isinstance(safeguard_receipt, SafeguardReceipt)
    action_digest = full_action_digest(action)
    acquisition_request = ResourceLockAcquisitionRequest.create(
        target_ref=action.target_resource_ref,
        action_digest=action_digest,
        attempt=attempt,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision=_SOURCE_REVISION,
    )
    acquisition = ResourceLockAcquisitionReceipt.create(
        lock_key=acquisition_request.lock_key,
        target_digest=acquisition_request.target_digest,
        action_digest=acquisition_request.action_digest,
        attempt=acquisition_request.attempt,
        provider_id="postgres-advisory-lock",
        provider_version="1.0.0",
        producer_id=acquisition_request.producer_id,
        producer_version=acquisition_request.producer_version,
        owner_token_digest="sha256:" + "2" * 64,
        fencing_generation=None,
        session_identity=f"session:{attempt}",
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="postgres:primary",
        acquired_at=now,
        valid_until=None,
        source_revision=acquisition_request.source_revision,
        request_digest=acquisition_request.request_digest,
    )
    lock_assessment = LiveLockOwnershipAssessment.create(
        acquisition,
        current_fencing_generation=None,
        current_session_identity=acquisition.session_identity,
        verifier_id="postgres-pg-locks-readback",
        verifier_version="1.0.0",
        trust_anchor_id=acquisition.trust_anchor_id,
        provider_attestation_digest="sha256:" + "4" * 64,
        evaluated_at=now,
        valid_until=now + timedelta(seconds=3),
    )
    lock_proof = LogicalTargetLockProof.create(
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        lock_key=safeguard_receipt.resource_lock_key,
        source_revision=_SOURCE_REVISION,
        completed_at=now,
        operation_receipt_digest=acquisition.receipt_digest,
    )
    reservation = IdempotencyReservationIdentity.create(
        idempotency_key=action.idempotency_key,
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        source_revision=_SOURCE_REVISION,
        acquisition_receipt=acquisition,
    )
    reserved = IdempotencyReservationRecord.create_reserved(
        identity=reservation,
        reserved_at=now,
        lease_expires_at=now + timedelta(seconds=30),
    )
    reservation_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reserved,
        expected_prior_revision=0,
        store_receipt_digest="sha256:" + "5" * 64,
        recorded_at=now,
    )
    intent = PreEffectAuditIntent.create(
        reservation_receipt=reservation_receipt,
        actor="fdai.core.executor",
        created_at=now,
    )
    audit_append_receipt = AuditIntentAppendReceipt.create(
        intent=intent,
        persisted_intent_digest=intent.intent_digest,
        store_receipt_digest="sha256:" + "6" * 64,
        persisted_at=now,
        read_back_at=now,
    )
    idempotency_proof = IdempotencyReservationProof.create(
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        idempotency_key=action.idempotency_key,
        reservation_outcome="reserved",
        source_revision=_SOURCE_REVISION,
        completed_at=now,
        store_receipt_digest=reservation_receipt.receipt_digest,
    )
    audit_intent_proof = AuditIntentProof.create(
        action_digest=action_digest,
        execution_path=safeguard_receipt.execution_path,
        execution_fingerprint=safeguard_receipt.execution_fingerprint,
        audit_entry_digest=intent.intent_digest,
        source_revision=_SOURCE_REVISION,
        completed_at=now,
        append_receipt_digest=audit_append_receipt.receipt_digest,
    )
    bundle = finalize_safeguard_proof_bundle(
        action,
        receipt=safeguard_receipt,
        source_revision=_SOURCE_REVISION,
        recorded_at=now,
        lock_proof=lock_proof,
        lock_assessment=lock_assessment,
        expected_lock_verifier_id=lock_assessment.verifier_id,
        expected_lock_verifier_version=lock_assessment.verifier_version,
        expected_lock_trust_anchor_id=lock_assessment.trust_anchor_id,
        idempotency_proof=idempotency_proof,
        audit_intent_proof=audit_intent_proof,
    )
    fence_identity = TargetDispatchFenceIdentity.create(
        target_digest=acquisition.target_digest,
        reservation_identity=reservation,
        continuity_policy=_policy(),
        generation=1,
        client_correlation_id="dispatch:1",
        sink_idempotency_key="sink:1",
    )
    preparing = TargetDispatchFenceRecord.create_preparing(
        identity=fence_identity,
        changed_at=now,
    )
    persistence_context = SafeguardBundlePersistenceContext(
        action=action,
        pre_bundle_commitment=SafeguardPreBundleCommitment.create(
            action=action,
            execution_path=safeguard_receipt.execution_path,
            source_revision=_SOURCE_REVISION,
            committed_at=now,
        ),
        safeguard_receipt=safeguard_receipt,
        reservation_receipt=reservation_receipt,
        audit_append_receipt=audit_append_receipt,
        lock_assessment=lock_assessment,
        lock_proof=lock_proof,
        idempotency_proof=idempotency_proof,
        audit_intent_proof=audit_intent_proof,
    )
    record = SafeguardDispatchEvidenceRecord.create_bundle_persisted(
        preparing_fence=preparing,
        persistence_context=persistence_context,
        bundle=bundle,
        persisted_at=now,
    )
    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=audit_append_receipt,
        safeguard_bundle_digest=bundle.bundle_digest,
        changed_at=now,
    )
    return (
        record,
        reservation,
        preparing,
        prepared,
        persistence_context,
    )


def _bundle_record() -> tuple[
    SafeguardDispatchEvidenceRecord,
    IdempotencyReservationIdentity,
]:
    record, reservation, _preparing, _prepared, _context = _evidence_fixture()
    return record, reservation


def _in_flight_reservation(
    context: SafeguardBundlePersistenceContext,
    *,
    at: datetime = _NOW,
) -> IdempotencyReservationTransitionReceipt:
    in_flight = begin_dispatch(
        context.reservation_receipt.record,
        at=at,
    )
    return IdempotencyReservationTransitionReceipt.create(
        prior_record=context.reservation_receipt.record,
        record=in_flight,
        expected_prior_revision=context.reservation_receipt.record.revision,
        store_receipt_digest="sha256:" + "8" * 64,
        recorded_at=at,
    )


def _bundle_persistence_receipt(
    record: SafeguardDispatchEvidenceRecord,
    *,
    at: datetime | None = None,
) -> SafeguardDispatchTransitionReceipt:
    return SafeguardDispatchTransitionReceipt.create(
        prior_record=None,
        record=record,
        store_receipt_digest="sha256:" + "b" * 64,
        recorded_at=at or record.state_changed_at,
    )


def _dispatch_started_record(
    record: SafeguardDispatchEvidenceRecord,
    *,
    prepared_fence: TargetDispatchFenceRecord | None = None,
    context: SafeguardBundlePersistenceContext | None = None,
    at: datetime = _NOW,
) -> tuple[SafeguardDispatchEvidenceRecord, SafeguardDispatchTransitionReceipt]:
    if prepared_fence is None or context is None:
        fixture_record, _reservation, _preparing, fixture_prepared, fixture_context = (
            _evidence_fixture()
        )
        assert fixture_record == record
        prepared_fence = fixture_prepared
        context = fixture_context
    persistence_receipt = _bundle_persistence_receipt(record)
    in_flight_fence = mark_target_fence_in_flight(
        prepared_fence,
        changed_at=at,
    )
    started = record_dispatch_start(
        record,
        bundle_persistence_receipt=persistence_receipt,
        in_flight_reservation_receipt=_in_flight_reservation(context, at=at),
        prepared_fence=prepared_fence,
        in_flight_fence=in_flight_fence,
        dispatch_started_at=at,
        changed_at=at,
    )
    return started, persistence_receipt


def _observation(
    record: SafeguardDispatchEvidenceRecord,
    *,
    transport: DispatchTransportState = DispatchTransportState.ACKNOWLEDGED,
    sink: AuthoritativeSinkState = AuthoritativeSinkState.ACCEPTED,
) -> tuple[SafeguardDispatchEvidenceRecord, SafeguardDispatchObservation]:
    started, _persistence_receipt = _dispatch_started_record(record)
    known = sink in {
        AuthoritativeSinkState.ACCEPTED,
        AuthoritativeSinkState.NOT_ACCEPTED,
        AuthoritativeSinkState.COMMITTED,
        AuthoritativeSinkState.NOT_COMMITTED,
    }
    accepted = sink in {
        AuthoritativeSinkState.ACCEPTED,
        AuthoritativeSinkState.COMMITTED,
    }
    observation = SafeguardDispatchObservation.create(
        dispatch_start_record=started,
        transport_state=transport,
        sink_state=sink,
        sink_operation_reference_digest=_DIGEST if accepted else None,
        authoritative_status_digest=_DIGEST if known else None,
        observed_at=_NOW + timedelta(seconds=1),
    )
    return started, observation


def _assessment(
    reservation: IdempotencyReservationIdentity,
    *,
    now: datetime = _NOW,
) -> LiveLockOwnershipAssessment:
    receipt = reservation.acquisition_receipt
    return LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=None,
        current_session_identity=receipt.session_identity,
        verifier_id="postgres-pg-locks-readback",
        verifier_version="1.0.0",
        trust_anchor_id=receipt.trust_anchor_id,
        provider_attestation_digest="sha256:" + "9" * 64,
        evaluated_at=now + timedelta(seconds=2),
        valid_until=now + timedelta(seconds=3),
    )


def test_exact_bundle_is_bound_before_dispatch() -> None:
    record, _reservation = _bundle_record()
    assert record.state is SafeguardDispatchEvidenceState.BUNDLE_PERSISTED
    assert record.bundle.bundle_digest == record.identity.safeguard_bundle_digest
    assert record.execution_authority is False
    assert record.effect_verified is False
    _base, _reservation, preparing, _prepared, context = _evidence_fixture()
    with pytest.raises(ValueError, match="backdated"):
        SafeguardDispatchEvidenceRecord.create_bundle_persisted(
            preparing_fence=preparing,
            persistence_context=context,
            bundle=record.bundle,
            persisted_at=_NOW - timedelta(microseconds=1),
        )
    wrong_bundle = _evidence_fixture(action_name="other")[0].bundle
    with pytest.raises(ValueError, match="operation proofs mismatched context"):
        SafeguardDispatchEvidenceRecord.create_bundle_persisted(
            preparing_fence=preparing,
            persistence_context=context,
            bundle=wrong_bundle,
            persisted_at=_NOW,
        )
    wrong_action_id = SafeguardProofBundle.create(
        action_id=UUID(int=99),
        execution_path=record.bundle.execution_path,
        execution_fingerprint=record.bundle.execution_fingerprint,
        source_revision=record.bundle.source_revision,
        recorded_at=record.bundle.recorded_at,
        proofs=record.bundle.proofs,
    )
    with pytest.raises(ValueError, match="reservation context mismatched fence"):
        SafeguardDispatchEvidenceRecord.create_bundle_persisted(
            preparing_fence=preparing,
            persistence_context=context,
            bundle=wrong_action_id,
            persisted_at=_NOW,
        )
    substituted_proofs = tuple(
        SafeguardProof(
            kind=proof.kind,
            proof_digest=(
                "sha256:" + "f" * 64
                if proof.kind is SafeguardProofKind.STOP_CONDITION
                else proof.proof_digest
            ),
        )
        for proof in record.bundle.proofs
    )
    substituted_bundle = SafeguardProofBundle.create(
        action_id=record.bundle.action_id,
        execution_path=record.bundle.execution_path,
        execution_fingerprint=record.bundle.execution_fingerprint,
        source_revision=record.bundle.source_revision,
        recorded_at=record.bundle.recorded_at,
        proofs=substituted_proofs,
    )
    with pytest.raises(ValueError, match="operation proofs mismatched context"):
        SafeguardDispatchEvidenceRecord.create_bundle_persisted(
            preparing_fence=preparing,
            persistence_context=context,
            bundle=substituted_bundle,
            persisted_at=_NOW,
        )
    tampered_context = replace(
        context,
        safeguard_receipt=replace(
            context.safeguard_receipt,
            dry_run_receipt="sha256:" + "e" * 64,
        ),
    )
    with pytest.raises(ValueError, match="safeguard receipt context mismatched"):
        SafeguardDispatchEvidenceRecord.create_bundle_persisted(
            preparing_fence=preparing,
            persistence_context=tampered_context,
            bundle=record.bundle,
            persisted_at=_NOW,
        )
    (
        _second_record,
        _second_reservation,
        second_preparing,
        _second_prepared,
        second_context,
    ) = _evidence_fixture(attempt=2)
    with pytest.raises(ValueError, match="operation proofs mismatched context"):
        SafeguardDispatchEvidenceRecord.create_bundle_persisted(
            preparing_fence=second_preparing,
            persistence_context=second_context,
            bundle=record.bundle,
            persisted_at=_NOW,
        )


def test_transport_acknowledgement_does_not_claim_sink_or_effect_success() -> None:
    record, _reservation = _bundle_record()
    started, observation = _observation(
        record,
        sink=AuthoritativeSinkState.UNOBSERVED,
    )
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    assert observation.transport_state is DispatchTransportState.ACKNOWLEDGED
    assert observation.sink_state is AuthoritativeSinkState.UNOBSERVED
    assert observation.effect_verified is False
    assert observed.independent_effect_state == "pending"


def test_authoritative_sink_state_requires_status_and_operation_reference() -> None:
    record, _reservation = _bundle_record()
    started, _persistence_receipt = _dispatch_started_record(record)
    with pytest.raises(ValueError, match="status evidence"):
        SafeguardDispatchObservation.create(
            dispatch_start_record=started,
            transport_state=DispatchTransportState.ACKNOWLEDGED,
            sink_state=AuthoritativeSinkState.ACCEPTED,
            sink_operation_reference_digest=_DIGEST,
            authoritative_status_digest=None,
            observed_at=_NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="operation reference"):
        SafeguardDispatchObservation.create(
            dispatch_start_record=started,
            transport_state=DispatchTransportState.ACKNOWLEDGED,
            sink_state=AuthoritativeSinkState.COMMITTED,
            sink_operation_reference_digest=None,
            authoritative_status_digest=_DIGEST,
            observed_at=_NOW + timedelta(seconds=1),
        )


def test_dispatch_cannot_begin_after_initial_lock_or_reservation_expiry() -> None:
    record, _reservation, preparing, _prepared, context = _evidence_fixture()
    late_prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=context.audit_append_receipt,
        safeguard_bundle_digest=record.bundle.bundle_digest,
        changed_at=record.identity.lock_assessment_valid_until,
    )
    late_in_flight = mark_target_fence_in_flight(
        late_prepared,
        changed_at=late_prepared.state_changed_at,
    )
    with pytest.raises(ValueError, match="requires exact current in-flight fence"):
        validate_dispatch_start(
            bundle_persistence_receipt=_bundle_persistence_receipt(record),
            in_flight_reservation_receipt=_in_flight_reservation(
                context,
                at=late_in_flight.state_changed_at,
            ),
            prepared_fence=late_prepared,
            in_flight_fence=late_in_flight,
            started_at=late_in_flight.state_changed_at,
        )
    with pytest.raises(ValueError, match="requires exact current in-flight fence"):
        record_dispatch_start(
            record,
            bundle_persistence_receipt=_bundle_persistence_receipt(record),
            in_flight_reservation_receipt=_in_flight_reservation(
                context,
                at=late_in_flight.state_changed_at,
            ),
            prepared_fence=late_prepared,
            in_flight_fence=late_in_flight,
            dispatch_started_at=late_in_flight.state_changed_at,
            changed_at=late_in_flight.state_changed_at,
        )


def test_dispatch_start_rejects_rewritten_in_flight_evidence() -> None:
    record, _reservation, _preparing, prepared, context = _evidence_fixture()
    rewritten = fence_model._build_record(  # noqa: SLF001
        identity=prepared.identity,
        state=fence_model.TargetDispatchFenceState.IN_FLIGHT,
        revision=prepared.revision + 1,
        prior_record_digest=prepared.record_digest,
        audit_append_receipt_digest="sha256:" + "8" * 64,
        safeguard_bundle_digest="sha256:" + "9" * 64,
        state_changed_at=prepared.state_changed_at,
    )
    with pytest.raises(ValueError, match="exact current in-flight fence"):
        validate_dispatch_start(
            bundle_persistence_receipt=_bundle_persistence_receipt(record),
            in_flight_reservation_receipt=_in_flight_reservation(context),
            prepared_fence=prepared,
            in_flight_fence=rewritten,
            started_at=_NOW,
        )
    with pytest.raises(ValueError, match="current in-flight reservation"):
        validate_dispatch_start(
            bundle_persistence_receipt=_bundle_persistence_receipt(record),
            in_flight_reservation_receipt=context.reservation_receipt,
            prepared_fence=prepared,
            in_flight_fence=mark_target_fence_in_flight(
                prepared,
                changed_at=_NOW,
            ),
            started_at=_NOW,
        )


def test_fresh_post_dispatch_ownership_reaches_pre_release() -> None:
    record, reservation = _bundle_record()
    started, observation = _observation(record)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    assessment = _assessment(reservation)
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=_NOW + timedelta(seconds=2),
    )
    pre_release = record_pre_release_checkpoint(
        observed,
        checkpoint=checkpoint,
        current_lock_assessment=assessment,
        changed_at=checkpoint.observed_at,
    )
    assert checkpoint.continuity_state is PreReleaseContinuityState.CURRENT
    assert pre_release.state is SafeguardDispatchEvidenceState.PRE_RELEASE
    validate_dispatch_evidence_transition(record, started)
    validate_dispatch_evidence_transition(started, observed)
    with pytest.raises(ValueError, match="current assessment is not exact"):
        validate_dispatch_evidence_transition(observed, pre_release)
    validate_dispatch_evidence_transition(
        observed,
        pre_release,
        current_lock_assessment=assessment,
    )
    assert checkpoint.valid_until is not None
    with pytest.raises(ValueError, match="is not current"):
        record_pre_release_checkpoint(
            observed,
            checkpoint=checkpoint,
            current_lock_assessment=assessment,
            changed_at=checkpoint.valid_until,
        )


@pytest.mark.parametrize(
    "reason",
    [
        ContinuityUnprovenReason.CALLBACK_CANCELLED,
        ContinuityUnprovenReason.CALLBACK_FAILED,
        ContinuityUnprovenReason.ASSESSMENT_FAILED,
        ContinuityUnprovenReason.MISSING,
    ],
)
def test_missing_or_failed_final_assessment_is_explicitly_unproven(
    reason: ContinuityUnprovenReason,
) -> None:
    record, _reservation = _bundle_record()
    checkpoint = PreReleaseOwnershipCheckpoint.unproven(
        evidence_identity=record.identity,
        reason=reason,
        observed_at=_NOW + timedelta(seconds=2),
    )
    assert checkpoint.continuity_state is PreReleaseContinuityState.CONTINUITY_UNPROVEN
    assert checkpoint.assessment_digest is None
    assert checkpoint.effect_verified is False


def test_ineligible_or_stale_assessment_is_unproven() -> None:
    record, reservation = _bundle_record()
    current = _assessment(reservation)
    ineligible = LiveLockOwnershipAssessment.create(
        current.acquisition_receipt,
        current_fencing_generation=None,
        current_session_identity=None,
        verifier_id=current.verifier_id,
        verifier_version=current.verifier_version,
        trust_anchor_id=current.trust_anchor_id,
        provider_attestation_digest="sha256:" + "8" * 64,
        evaluated_at=current.evaluated_at,
        valid_until=current.valid_until,
        rejection_reasons=(LockOwnershipRejectionReason.LOCK_LOST,),
    )
    lost = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=ineligible,
        not_before=_NOW + timedelta(seconds=1),
        observed_at=ineligible.evaluated_at,
    )
    stale = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=current,
        not_before=_NOW + timedelta(seconds=1),
        observed_at=current.valid_until,
    )
    assert lost.unproven_reason is ContinuityUnprovenReason.INELIGIBLE
    assert stale.unproven_reason is ContinuityUnprovenReason.STALE


def test_pre_dispatch_assessment_is_continuity_unproven() -> None:
    record, reservation = _bundle_record()
    _started, observation = _observation(record)
    receipt = reservation.acquisition_receipt
    early = LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=None,
        current_session_identity=receipt.session_identity,
        verifier_id="postgres-pg-locks-readback",
        verifier_version="1.0.0",
        trust_anchor_id=receipt.trust_anchor_id,
        provider_attestation_digest="sha256:" + "7" * 64,
        evaluated_at=_NOW,
        valid_until=_NOW + timedelta(seconds=3),
    )
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=early,
        not_before=observation.observed_at,
        observed_at=_NOW + timedelta(seconds=2),
    )
    assert checkpoint.unproven_reason is ContinuityUnprovenReason.STALE


def test_untrusted_pre_release_verifier_is_continuity_unproven() -> None:
    record, reservation = _bundle_record()
    _started, observation = _observation(record)
    receipt = reservation.acquisition_receipt
    untrusted = LiveLockOwnershipAssessment.create(
        receipt,
        current_fencing_generation=None,
        current_session_identity=receipt.session_identity,
        verifier_id="untrusted-verifier",
        verifier_version="0.0.0",
        trust_anchor_id=receipt.trust_anchor_id,
        provider_attestation_digest="sha256:" + "7" * 64,
        evaluated_at=_NOW + timedelta(seconds=2),
        valid_until=_NOW + timedelta(seconds=3),
    )
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=untrusted,
        not_before=observation.observed_at,
        observed_at=_NOW + timedelta(seconds=2),
    )
    assert checkpoint.unproven_reason is ContinuityUnprovenReason.ASSESSMENT_FAILED


def test_transition_rejects_observation_or_bundle_substitution() -> None:
    record, _reservation = _bundle_record()
    started, observation = _observation(record)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(observation, observation_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="bundle changed"):
        validate_dispatch_evidence_transition(
            started,
            replace(
                observed,
                bundle=_evidence_fixture(action_name="other")[0].bundle,
                record_digest=observed.record_digest,
            ),
        )


def test_observation_binds_exact_persisted_bundle_record() -> None:
    record, _reservation, preparing, _prepared, context = _evidence_fixture()
    _started, observation = _observation(record)
    later_record = SafeguardDispatchEvidenceRecord.create_bundle_persisted(
        preparing_fence=preparing,
        persistence_context=context,
        bundle=record.bundle,
        persisted_at=_NOW + timedelta(seconds=2),
    )
    later_prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=context.audit_append_receipt,
        safeguard_bundle_digest=record.bundle.bundle_digest,
        changed_at=_NOW + timedelta(seconds=2),
    )
    later_started, _later_receipt = _dispatch_started_record(
        later_record,
        prepared_fence=later_prepared,
        context=context,
        at=_NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValueError, match="changed dispatch start"):
        record_dispatch_observation(
            later_started,
            observation=observation,
            changed_at=_NOW + timedelta(seconds=2),
        )
    later_observation = SafeguardDispatchObservation.create(
        dispatch_start_record=later_started,
        transport_state=DispatchTransportState.UNKNOWN,
        sink_state=AuthoritativeSinkState.UNKNOWN,
        sink_operation_reference_digest=None,
        authoritative_status_digest=None,
        observed_at=_NOW + timedelta(seconds=2),
    )
    assert later_observation.bundle_record_digest == later_record.record_digest


def test_continuity_unproven_checkpoint_cannot_predate_dispatch() -> None:
    record, _reservation = _bundle_record()
    started, observation = _observation(record)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    checkpoint = PreReleaseOwnershipCheckpoint.unproven(
        evidence_identity=record.identity,
        reason=ContinuityUnprovenReason.CALLBACK_FAILED,
        observed_at=_NOW,
    )
    with pytest.raises(ValueError, match="predates dispatch"):
        record_pre_release_checkpoint(
            observed,
            checkpoint=checkpoint,
            changed_at=observation.observed_at,
        )


def test_safeguard_dispatch_codec_round_trips_pre_release_record() -> None:
    record, reservation = _bundle_record()
    started, observation = _observation(record)
    observed = record_dispatch_observation(
        started,
        observation=observation,
        changed_at=observation.observed_at,
    )
    assessment = _assessment(reservation)
    checkpoint = PreReleaseOwnershipCheckpoint.from_assessment(
        evidence_identity=record.identity,
        assessment=assessment,
        not_before=observation.observed_at,
        observed_at=_NOW + timedelta(seconds=2),
    )
    pre_release = record_pre_release_checkpoint(
        observed,
        checkpoint=checkpoint,
        current_lock_assessment=assessment,
        changed_at=checkpoint.observed_at,
    )
    mapping = safeguard_dispatch_record_to_mapping(pre_release)
    assert safeguard_dispatch_record_from_mapping(mapping) == pre_release
    with pytest.raises(ValueError, match="fields are invalid"):
        safeguard_dispatch_record_from_mapping({**mapping, "unexpected": True})
