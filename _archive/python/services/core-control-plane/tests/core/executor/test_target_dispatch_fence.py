"""Target-wide prepared dispatch fence contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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
)
from fdai.core.executor.lock_continuity import (
    EffectSinkContinuityPolicy,
    OwnershipContinuityStrategy,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
    TargetDispatchFenceTransitionReceipt,
    attach_prepared_evidence,
    close_target_fence_after_release,
    mark_target_fence_in_flight,
    mark_target_fence_release_pending,
    resolve_target_fence_without_dispatch,
)
from fdai.core.executor.target_dispatch_fence_codec import (
    target_dispatch_fence_from_mapping,
    target_dispatch_fence_to_mapping,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceAcquireDecision,
    TargetDispatchFenceAcquireResult,
    classify_target_fence,
    target_mutation_blocked,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)

_NOW = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64


def _reservation_identity(
    *,
    target_ref: str = "resource/example",
    attempt: int = 1,
    acquired_at: datetime = _NOW,
) -> IdempotencyReservationIdentity:
    request = ResourceLockAcquisitionRequest.create(
        target_ref=target_ref,
        action_digest="sha256:" + "1" * 64,
        attempt=attempt,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "b" * 40,
    )
    acquisition = ResourceLockAcquisitionReceipt.create(
        lock_key=request.lock_key,
        target_digest=request.target_digest,
        action_digest=request.action_digest,
        attempt=request.attempt,
        provider_id="postgres-advisory-lock",
        provider_version="1.0.0",
        producer_id=request.producer_id,
        producer_version=request.producer_version,
        owner_token_digest="sha256:" + "2" * 64,
        fencing_generation=None,
        session_identity=f"session:{attempt}",
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="postgres:primary",
        acquired_at=acquired_at,
        valid_until=None,
        source_revision=request.source_revision,
        request_digest=request.request_digest,
    )
    return IdempotencyReservationIdentity.create(
        idempotency_key="example-idempotency",
        action_digest=request.action_digest,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint="4" * 64,
        source_revision=request.source_revision,
        acquisition_receipt=acquisition,
    )


def _policy() -> EffectSinkContinuityPolicy:
    return EffectSinkContinuityPolicy.create(
        sink_id="example-sink",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.QUARANTINED_RECONCILIATION,
        cancellation_supported=True,
        durable_unknown_quarantine=True,
        reconciliation_supported=True,
    )


def _identity(
    *,
    generation: int = 1,
    reservation_identity: IdempotencyReservationIdentity | None = None,
) -> TargetDispatchFenceIdentity:
    reservation = reservation_identity or _reservation_identity()
    return TargetDispatchFenceIdentity.create(
        target_digest=reservation.acquisition_receipt.target_digest,
        reservation_identity=reservation,
        continuity_policy=_policy(),
        generation=generation,
        client_correlation_id=f"dispatch:{generation}",
        sink_idempotency_key=f"sink:{generation}",
    )


def _audit_receipt(
    reservation_identity: IdempotencyReservationIdentity,
    *,
    persisted_at: datetime = _NOW,
    read_back_at: datetime = _NOW,
) -> AuditIntentAppendReceipt:
    reservation = IdempotencyReservationRecord.create_reserved(
        identity=reservation_identity,
        reserved_at=_NOW,
        lease_expires_at=_NOW + timedelta(minutes=1),
    )
    reservation_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reservation,
        expected_prior_revision=0,
        store_receipt_digest="sha256:" + "5" * 64,
        recorded_at=_NOW,
    )
    intent = PreEffectAuditIntent.create(
        reservation_receipt=reservation_receipt,
        actor="fdai.core.executor",
        created_at=_NOW,
    )
    return AuditIntentAppendReceipt.create(
        intent=intent,
        persisted_intent_digest=intent.intent_digest,
        store_receipt_digest="sha256:" + "6" * 64,
        persisted_at=persisted_at,
        read_back_at=read_back_at,
    )


def _preparing() -> TargetDispatchFenceRecord:
    return TargetDispatchFenceRecord.create_preparing(
        identity=_identity(),
        changed_at=_NOW,
    )


def _prepared() -> TargetDispatchFenceRecord:
    preparing = _preparing()
    return attach_prepared_evidence(
        preparing,
        audit_append_receipt=_audit_receipt(_reservation_identity()),
        safeguard_bundle_digest="sha256:" + "7" * 64,
        changed_at=_NOW,
    )


def test_target_fence_lifecycle_is_monotonic_and_target_wide() -> None:
    preparing = _preparing()
    prepared = _prepared()
    in_flight = mark_target_fence_in_flight(prepared, changed_at=_NOW)
    release_pending = mark_target_fence_release_pending(
        in_flight,
        changed_at=_NOW,
    )
    quarantined = close_target_fence_after_release(
        release_pending,
        quarantined=True,
        resolution_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    resolved = close_target_fence_after_release(
        quarantined,
        quarantined=False,
        resolution_evidence_digest="sha256:" + "8" * 64,
        changed_at=_NOW,
    )

    assert [
        record.revision
        for record in (
            preparing,
            prepared,
            in_flight,
            release_pending,
            quarantined,
            resolved,
        )
    ] == [1, 2, 3, 4, 5, 6]
    assert target_mutation_blocked(None) is False
    assert target_mutation_blocked(preparing) is True
    assert target_mutation_blocked(quarantined) is True
    assert target_mutation_blocked(resolved) is False
    assert resolved.execution_authority is False
    assert resolved.effect_verified is False


def test_prepared_evidence_requires_exact_reservation() -> None:
    preparing = _preparing()
    with pytest.raises(ValueError, match="changed reservation"):
        attach_prepared_evidence(
            preparing,
            audit_append_receipt=_audit_receipt(
                _reservation_identity(target_ref="resource/other"),
            ),
            safeguard_bundle_digest="sha256:" + "7" * 64,
            changed_at=_NOW,
        )
    with pytest.raises(ValueError, match="before audit readback"):
        attach_prepared_evidence(
            preparing,
            audit_append_receipt=_audit_receipt(
                _reservation_identity(),
                persisted_at=_NOW + timedelta(seconds=1),
                read_back_at=_NOW + timedelta(seconds=2),
            ),
            safeguard_bundle_digest="sha256:" + "7" * 64,
            changed_at=_NOW + timedelta(seconds=1),
        )


def test_no_dispatch_closure_requires_authoritative_evidence() -> None:
    preparing = _preparing()
    resolved = resolve_target_fence_without_dispatch(
        preparing,
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    assert resolved.state is TargetDispatchFenceState.RESOLVED
    assert target_mutation_blocked(resolved) is False
    with pytest.raises(ValueError):
        resolve_target_fence_without_dispatch(
            preparing,
            no_dispatch_evidence_digest="invalid",
            changed_at=_NOW,
        )


def test_prepared_no_dispatch_closure_clears_prerequisites() -> None:
    resolved = resolve_target_fence_without_dispatch(
        _prepared(),
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    assert resolved.audit_append_receipt_digest is None
    assert resolved.safeguard_bundle_digest is None


def test_new_generation_requires_resolved_predecessor_and_later_acquisition() -> None:
    resolved = resolve_target_fence_without_dispatch(
        _preparing(),
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    next_reservation = _reservation_identity(
        attempt=2,
        acquired_at=_NOW + timedelta(seconds=1),
    )
    next_record = TargetDispatchFenceRecord.create_preparing(
        identity=_identity(
            generation=2,
            reservation_identity=next_reservation,
        ),
        changed_at=_NOW + timedelta(seconds=1),
        prior_resolved_record=resolved,
    )
    assert next_record.identity.generation == 2
    assert next_record.prior_record_digest == resolved.record_digest
    transition = TargetDispatchFenceTransitionReceipt.create(
        prior_record=resolved,
        record=next_record,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    assert transition.record == next_record

    with pytest.raises(ValueError, match="requires resolved"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(
                generation=2,
                reservation_identity=next_reservation,
            ),
            changed_at=_NOW + timedelta(seconds=1),
            prior_resolved_record=_preparing(),
        )
    with pytest.raises(ValueError, match="requires a later acquisition"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(
                generation=2,
                reservation_identity=_reservation_identity(),
            ),
            changed_at=_NOW,
            prior_resolved_record=resolved,
        )


def test_duplicate_and_blocked_acquisition_are_candidate_bound() -> None:
    preparing = _preparing()
    same = preparing.identity
    other = _identity(
        reservation_identity=_reservation_identity(
            attempt=2,
            acquired_at=_NOW + timedelta(seconds=1),
        )
    )
    assert (
        classify_target_fence(preparing, same) is TargetDispatchFenceAcquireDecision.DUPLICATE_SAME
    )
    assert classify_target_fence(preparing, other) is TargetDispatchFenceAcquireDecision.BLOCKED

    duplicate = TargetDispatchFenceAcquireResult(
        candidate_identity=same,
        decision=TargetDispatchFenceAcquireDecision.DUPLICATE_SAME,
        observed_record=preparing,
        transition_receipt=None,
    )
    assert duplicate.transition_receipt is None


def test_initial_and_acquired_evidence_require_generation_one_preparing() -> None:
    preparing = _preparing()
    initial_receipt = TargetDispatchFenceTransitionReceipt.create(
        prior_record=None,
        record=preparing,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    acquired = TargetDispatchFenceAcquireResult(
        candidate_identity=preparing.identity,
        decision=TargetDispatchFenceAcquireDecision.ACQUIRED,
        observed_record=preparing,
        transition_receipt=initial_receipt,
    )
    assert acquired.observed_record is preparing

    prepared = _prepared()
    transition = TargetDispatchFenceTransitionReceipt.create(
        prior_record=_preparing(),
        record=prepared,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    with pytest.raises(ValueError, match="requires exact insert evidence"):
        TargetDispatchFenceAcquireResult(
            candidate_identity=prepared.identity,
            decision=TargetDispatchFenceAcquireDecision.ACQUIRED,
            observed_record=prepared,
            transition_receipt=transition,
        )


def test_transition_receipt_binds_exact_predecessor() -> None:
    preparing = _preparing()
    prepared = attach_prepared_evidence(
        preparing,
        audit_append_receipt=_audit_receipt(_reservation_identity()),
        safeguard_bundle_digest="sha256:" + "7" * 64,
        changed_at=_NOW,
    )
    receipt = TargetDispatchFenceTransitionReceipt.create(
        prior_record=preparing,
        record=prepared,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    assert receipt.record == prepared
    with pytest.raises(ValueError, match="predecessor mismatched"):
        TargetDispatchFenceTransitionReceipt.create(
            prior_record=preparing,
            record=mark_target_fence_release_pending(
                mark_target_fence_in_flight(prepared, changed_at=_NOW),
                changed_at=_NOW,
            ),
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )


def test_transition_helpers_reject_skipped_or_reversed_edges() -> None:
    with pytest.raises(ValueError, match="not prepared"):
        mark_target_fence_in_flight(_preparing(), changed_at=_NOW)
    with pytest.raises(ValueError, match="not in flight"):
        mark_target_fence_release_pending(_prepared(), changed_at=_NOW)
    release_pending = mark_target_fence_release_pending(
        mark_target_fence_in_flight(_prepared(), changed_at=_NOW),
        changed_at=_NOW,
    )
    with pytest.raises(ValueError, match="not prepared"):
        mark_target_fence_in_flight(release_pending, changed_at=_NOW)
    quarantined = close_target_fence_after_release(
        release_pending,
        quarantined=True,
        resolution_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    with pytest.raises(ValueError, match="requires resolution"):
        close_target_fence_after_release(
            quarantined,
            quarantined=True,
            resolution_evidence_digest=_DIGEST,
            changed_at=_NOW,
        )
    with pytest.raises(ValueError, match="fresh reconciliation evidence"):
        close_target_fence_after_release(
            quarantined,
            quarantined=False,
            resolution_evidence_digest=_DIGEST,
            changed_at=_NOW,
        )


def test_fence_rejects_unsupported_continuity_strategy() -> None:
    reservation = _reservation_identity()
    policy = EffectSinkContinuityPolicy.create(
        sink_id="example-sink",
        sink_version="1.0.0",
        strategy=OwnershipContinuityStrategy.FENCED_IDEMPOTENT,
        sink_fencing=True,
        stable_sink_idempotency=True,
    )
    with pytest.raises(ValueError, match="quarantined reconciliation only"):
        TargetDispatchFenceIdentity.create(
            target_digest=reservation.acquisition_receipt.target_digest,
            reservation_identity=reservation,
            continuity_policy=policy,
            generation=1,
            client_correlation_id="dispatch:1",
            sink_idempotency_key="sink:1",
        )


def test_target_fence_codec_round_trip_and_corruption() -> None:
    record = mark_target_fence_in_flight(_prepared(), changed_at=_NOW)
    mapping = target_dispatch_fence_to_mapping(record)
    assert target_dispatch_fence_from_mapping(mapping) == record

    with pytest.raises(ValueError, match="fields are invalid"):
        target_dispatch_fence_from_mapping({**mapping, "unexpected": True})
    with pytest.raises(ValueError, match="digest mismatched"):
        target_dispatch_fence_from_mapping(
            {
                **mapping,
                "record_digest": "sha256:" + "0" * 64,
            }
        )


def test_store_symbols_keep_the_original_public_import_path() -> None:
    from fdai.core.executor import target_dispatch_fence as original_module

    assert original_module.TargetDispatchFenceAcquireDecision is TargetDispatchFenceAcquireDecision
    assert original_module.classify_target_fence is classify_target_fence
    assert original_module.target_mutation_blocked is target_mutation_blocked


def test_transition_receipt_rejects_prepared_evidence_substitution() -> None:
    prepared = _prepared()
    substituted = fence_model._build_record(  # noqa: SLF001
        identity=prepared.identity,
        state=TargetDispatchFenceState.IN_FLIGHT,
        revision=prepared.revision + 1,
        prior_record_digest=prepared.record_digest,
        audit_append_receipt_digest="sha256:" + "8" * 64,
        safeguard_bundle_digest="sha256:" + "9" * 64,
        state_changed_at=prepared.state_changed_at,
    )
    with pytest.raises(ValueError, match="prepared evidence was rewritten"):
        TargetDispatchFenceTransitionReceipt.create(
            prior_record=prepared,
            record=substituted,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )


def test_transition_receipt_rejects_pre_dispatch_resolution_substitution() -> None:
    preparing = _preparing()
    substituted = fence_model._build_record(  # noqa: SLF001
        identity=preparing.identity,
        state=TargetDispatchFenceState.RESOLVED,
        revision=preparing.revision + 1,
        prior_record_digest=preparing.record_digest,
        audit_append_receipt_digest="sha256:" + "8" * 64,
        safeguard_bundle_digest="sha256:" + "9" * 64,
        state_changed_at=preparing.state_changed_at,
        resolution_evidence_digest=_DIGEST,
    )
    with pytest.raises(ValueError, match="pre-dispatch closure evidence is invalid"):
        TargetDispatchFenceTransitionReceipt.create(
            prior_record=preparing,
            record=substituted,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )


def test_transition_receipt_requires_fresh_quarantine_reconciliation() -> None:
    release_pending = mark_target_fence_release_pending(
        mark_target_fence_in_flight(_prepared(), changed_at=_NOW),
        changed_at=_NOW,
    )
    quarantined = close_target_fence_after_release(
        release_pending,
        quarantined=True,
        resolution_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    reconstructed = fence_model._build_record(  # noqa: SLF001
        identity=quarantined.identity,
        state=TargetDispatchFenceState.RESOLVED,
        revision=quarantined.revision + 1,
        prior_record_digest=quarantined.record_digest,
        audit_append_receipt_digest=quarantined.audit_append_receipt_digest,
        safeguard_bundle_digest=quarantined.safeguard_bundle_digest,
        state_changed_at=quarantined.state_changed_at,
        resolution_evidence_digest=quarantined.resolution_evidence_digest,
    )
    with pytest.raises(ValueError, match="is not fresh"):
        TargetDispatchFenceTransitionReceipt.create(
            prior_record=quarantined,
            record=reconstructed,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "2.0.0"}, "unsupported"),
        ({"execution_authority": True}, "MUST NOT grant authority"),
        ({"effect_verification_authority": True}, "MUST NOT grant authority"),
        ({"reservation_attempt": 0}, "attempt MUST be positive"),
        ({"generation": 0}, "generation MUST be positive"),
        ({"client_correlation_id": ""}, "canonical and bounded"),
        ({"sink_idempotency_key": " padded "}, "canonical and bounded"),
        ({"identity_digest": "sha256:" + "0" * 64}, "digest mismatched"),
    ),
)
def test_target_fence_identity_rejects_invalid_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_identity(), **cast(Any, changes))


def test_target_fence_identity_factory_rejects_invalid_inputs() -> None:
    reservation = _reservation_identity()

    class DerivedIdentity(TargetDispatchFenceIdentity):
        pass

    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedIdentity.create(
            target_digest=reservation.acquisition_receipt.target_digest,
            reservation_identity=reservation,
            continuity_policy=_policy(),
            generation=1,
            client_correlation_id="dispatch:1",
            sink_idempotency_key="sink:1",
        )
    with pytest.raises(ValueError, match="exact reservation identity"):
        TargetDispatchFenceIdentity.create(
            target_digest=reservation.acquisition_receipt.target_digest,
            reservation_identity=cast(Any, object()),
            continuity_policy=_policy(),
            generation=1,
            client_correlation_id="dispatch:1",
            sink_idempotency_key="sink:1",
        )
    with pytest.raises(ValueError, match="target mismatched acquisition"):
        TargetDispatchFenceIdentity.create(
            target_digest="sha256:" + "0" * 64,
            reservation_identity=reservation,
            continuity_policy=_policy(),
            generation=1,
            client_correlation_id="dispatch:1",
            sink_idempotency_key="sink:1",
        )
    with pytest.raises(ValueError, match="exact continuity policy"):
        TargetDispatchFenceIdentity.create(
            target_digest=reservation.acquisition_receipt.target_digest,
            reservation_identity=reservation,
            continuity_policy=cast(Any, object()),
            generation=1,
            client_correlation_id="dispatch:1",
            sink_idempotency_key="sink:1",
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (lambda record: replace(record, schema_version="2.0.0"), "unsupported"),
        (lambda record: replace(record, execution_authority=True), "MUST NOT grant authority"),
        (lambda record: replace(record, effect_verified=True), "MUST NOT grant authority"),
        (lambda record: replace(record, identity=cast(Any, object())), "exact identity"),
        (lambda record: replace(record, state=cast(Any, "preparing")), "state is invalid"),
        (lambda record: replace(record, revision=0), "revision MUST be positive"),
        (
            lambda record: replace(record, prior_record_digest=_DIGEST),
            "MUST NOT have a predecessor",
        ),
        (
            lambda record: replace(
                record,
                state_changed_at=record.identity.acquisition_acquired_at
                - timedelta(microseconds=1),
            ),
            "predates lock acquisition",
        ),
        (
            lambda record: replace(
                record,
                audit_append_receipt_digest=_DIGEST,
            ),
            "prerequisites are partial",
        ),
        (
            lambda record: replace(record, record_digest="sha256:" + "0" * 64),
            "digest mismatched",
        ),
    ),
)
def test_target_fence_record_rejects_invalid_fields(
    factory: Any,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory(_preparing())


def test_target_fence_record_factory_rejects_invalid_generation_inputs() -> None:
    preparing = _preparing()
    resolved = resolve_target_fence_without_dispatch(
        preparing,
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )

    class DerivedRecord(TargetDispatchFenceRecord):
        pass

    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedRecord.create_preparing(identity=_identity(), changed_at=_NOW)
    with pytest.raises(ValueError, match="generation MUST be one"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(generation=2),
            changed_at=_NOW,
        )
    with pytest.raises(ValueError, match="predecessor is invalid"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(),
            changed_at=_NOW,
            prior_resolved_record=cast(Any, object()),
        )
    with pytest.raises(ValueError, match="requires resolved predecessor"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(),
            changed_at=_NOW,
            prior_resolved_record=preparing,
        )
    later_reservation = _reservation_identity(
        attempt=2,
        acquired_at=_NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="generation MUST increase by one"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(
                generation=3,
                reservation_identity=later_reservation,
            ),
            changed_at=_NOW + timedelta(seconds=1),
            prior_resolved_record=resolved,
        )
    with pytest.raises(ValueError, match="changes target"):
        TargetDispatchFenceRecord.create_preparing(
            identity=_identity(
                generation=2,
                reservation_identity=_reservation_identity(
                    target_ref="resource/other",
                    attempt=2,
                    acquired_at=_NOW + timedelta(seconds=1),
                ),
            ),
            changed_at=_NOW + timedelta(seconds=1),
            prior_resolved_record=resolved,
        )


def test_target_fence_public_transitions_reject_stale_or_wrong_state() -> None:
    preparing = _preparing()
    prepared = _prepared()
    in_flight = mark_target_fence_in_flight(prepared, changed_at=_NOW)
    release_pending = mark_target_fence_release_pending(
        in_flight,
        changed_at=_NOW,
    )

    with pytest.raises(ValueError, match="cannot resolve as undispatched"):
        resolve_target_fence_without_dispatch(
            release_pending,
            no_dispatch_evidence_digest=_DIGEST,
            changed_at=_NOW,
        )
    recovered = resolve_target_fence_without_dispatch(
        in_flight,
        no_dispatch_evidence_digest=_DIGEST,
        changed_at=_NOW,
    )
    assert recovered.state is TargetDispatchFenceState.RESOLVED
    assert recovered.no_dispatch_evidence_digest == _DIGEST
    with pytest.raises(ValueError, match="no_dispatch_evidence_digest"):
        resolve_target_fence_without_dispatch(
            preparing,
            no_dispatch_evidence_digest="invalid",
            changed_at=_NOW,
        )
    with pytest.raises(ValueError, match="not terminalizable"):
        close_target_fence_after_release(
            prepared,
            quarantined=False,
            resolution_evidence_digest=_DIGEST,
            changed_at=_NOW,
        )
    with pytest.raises(ValueError, match="transition is backdated"):
        mark_target_fence_in_flight(
            prepared,
            changed_at=prepared.state_changed_at - timedelta(microseconds=1),
        )
    with pytest.raises(ValueError, match="requires predecessor digest"):
        replace(prepared, prior_record_digest=None)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "2.0.0"}, "unsupported"),
        ({"execution_authority": True}, "MUST NOT grant authority"),
        ({"record": object()}, "requires an exact record"),
        ({"prior_record": object()}, "predecessor is invalid"),
        ({"recorded_at": _NOW - timedelta(microseconds=1)}, "backdated"),
        ({"receipt_digest": "sha256:" + "0" * 64}, "digest mismatched"),
    ),
)
def test_target_fence_transition_receipt_rejects_invalid_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    preparing = _preparing()
    receipt = TargetDispatchFenceTransitionReceipt.create(
        prior_record=None,
        record=preparing,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    if "prior_record" in changes:
        prepared = _prepared()
        receipt = TargetDispatchFenceTransitionReceipt.create(
            prior_record=preparing,
            record=prepared,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )

    with pytest.raises(ValueError, match=message):
        replace(receipt, **cast(Any, changes))


def test_target_fence_transition_factory_and_initial_shape_fail_closed() -> None:
    preparing = _preparing()

    class DerivedReceipt(TargetDispatchFenceTransitionReceipt):
        pass

    with pytest.raises(TypeError, match="does not support subclasses"):
        DerivedReceipt.create(
            prior_record=None,
            record=preparing,
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )
    with pytest.raises(ValueError, match="initial target dispatch fence transition is invalid"):
        TargetDispatchFenceTransitionReceipt.create(
            prior_record=None,
            record=_prepared(),
            store_receipt_digest=_DIGEST,
            recorded_at=_NOW,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"candidate_identity": object()}, "exact candidate"),
        ({"decision": "acquired"}, "decision is invalid"),
        ({"observed_record": object()}, "exact record"),
        ({"transition_receipt": None}, "requires exact insert evidence"),
    ),
)
def test_target_fence_acquire_result_rejects_invalid_evidence(
    changes: dict[str, object],
    message: str,
) -> None:
    preparing = _preparing()
    receipt = TargetDispatchFenceTransitionReceipt.create(
        prior_record=None,
        record=preparing,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )
    values: dict[str, object] = {
        "candidate_identity": preparing.identity,
        "decision": TargetDispatchFenceAcquireDecision.ACQUIRED,
        "observed_record": preparing,
        "transition_receipt": receipt,
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        TargetDispatchFenceAcquireResult(**cast(Any, values))


def test_target_fence_classifier_and_observed_result_reject_mismatch() -> None:
    preparing = _preparing()
    wrong_target = _identity(
        reservation_identity=_reservation_identity(target_ref="resource/other")
    )
    other_attempt = _identity(
        reservation_identity=_reservation_identity(
            attempt=2,
            acquired_at=_NOW + timedelta(seconds=1),
        )
    )
    receipt = TargetDispatchFenceTransitionReceipt.create(
        prior_record=None,
        record=preparing,
        store_receipt_digest=_DIGEST,
        recorded_at=_NOW,
    )

    with pytest.raises(ValueError, match="target mismatched"):
        classify_target_fence(preparing, wrong_target)
    with pytest.raises(ValueError, match="MUST NOT claim insert evidence"):
        TargetDispatchFenceAcquireResult(
            candidate_identity=preparing.identity,
            decision=TargetDispatchFenceAcquireDecision.DUPLICATE_SAME,
            observed_record=preparing,
            transition_receipt=receipt,
        )
    with pytest.raises(ValueError, match="mismatched candidate"):
        TargetDispatchFenceAcquireResult(
            candidate_identity=other_attempt,
            decision=TargetDispatchFenceAcquireDecision.DUPLICATE_SAME,
            observed_record=preparing,
            transition_receipt=None,
        )


def test_target_fence_lazy_store_export_rejects_unknown_symbol() -> None:
    assert fence_model.__getattr__("target_mutation_blocked") is target_mutation_blocked
    with pytest.raises(AttributeError, match="has no attribute"):
        fence_model.__getattr__("unknown_symbol")
