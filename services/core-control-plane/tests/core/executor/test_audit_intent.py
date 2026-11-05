"""Authoritative pre-effect audit-intent contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    AuditIntentAppendReceipt,
    AuditIntentAppendResult,
    PreEffectAuditIntent,
    _normalize_digest_value,
    audit_intent_to_mapping,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationTransitionReceipt,
    begin_dispatch,
)
from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import (
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
)

_NOW = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "a" * 64


def _reservation_receipt() -> IdempotencyReservationTransitionReceipt:
    request = ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "1" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision="commit:" + "b" * 40,
    )
    acquisition = ResourceLockAcquisitionReceipt.create(
        lock_key=request.lock_key,
        target_digest=request.target_digest,
        action_digest=request.action_digest,
        attempt=request.attempt,
        provider_id="local-resource-lock",
        provider_version="1.0.0",
        producer_id=request.producer_id,
        producer_version=request.producer_version,
        owner_token_digest="sha256:" + "2" * 64,
        fencing_generation=None,
        session_identity="session:example",
        provider_attestation_digest="sha256:" + "3" * 64,
        trust_anchor_id="fdai:local-test-only",
        acquired_at=_NOW,
        valid_until=None,
        source_revision=request.source_revision,
        request_digest=request.request_digest,
    )
    identity = IdempotencyReservationIdentity.create(
        idempotency_key="example-idempotency",
        action_digest=request.action_digest,
        execution_path=ExecutionPath.DIRECT_API,
        execution_fingerprint="4" * 64,
        source_revision=request.source_revision,
        acquisition_receipt=acquisition,
    )
    reservation = IdempotencyReservationRecord.create_reserved(
        identity=identity,
        reserved_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=10),
    )
    return IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=reservation,
        expected_prior_revision=0,
        store_receipt_digest="sha256:" + "5" * 64,
        recorded_at=_NOW,
    )


def _intent() -> PreEffectAuditIntent:
    return PreEffectAuditIntent.create(
        reservation_receipt=_reservation_receipt(),
        actor="fdai.core.executor",
        created_at=_NOW + timedelta(seconds=1),
    )


def _append_receipt() -> AuditIntentAppendReceipt:
    intent = _intent()
    return AuditIntentAppendReceipt.create(
        intent=intent,
        persisted_intent_digest=intent.intent_digest,
        store_receipt_digest="sha256:" + "6" * 64,
        persisted_at=_NOW + timedelta(seconds=2),
        read_back_at=_NOW + timedelta(seconds=3),
    )


def test_audit_intent_binds_reservation_acquisition_and_context() -> None:
    intent = _intent()
    reservation = intent.reservation_receipt.record

    assert reservation.identity.action_digest == "sha256:" + "1" * 64
    assert reservation.identity.execution_path is ExecutionPath.DIRECT_API
    assert (
        reservation.identity.acquisition_receipt.receipt_digest
        == intent.reservation_receipt.record.identity.acquisition_receipt.receipt_digest
    )
    assert intent.execution_authority is False
    assert intent.effect_verified is False


def test_append_receipt_requires_exact_authoritative_readback() -> None:
    intent = _intent()
    with pytest.raises(ValueError, match="readback mismatched"):
        AuditIntentAppendReceipt.create(
            intent=intent,
            persisted_intent_digest="sha256:" + "9" * 64,
            store_receipt_digest="sha256:" + "6" * 64,
            persisted_at=_NOW + timedelta(seconds=2),
            read_back_at=_NOW + timedelta(seconds=3),
        )

    receipt = _append_receipt()
    assert receipt.execution_authority is False
    assert receipt.effect_verified is False


def test_append_result_distinguishes_success_duplicate_and_conflict() -> None:
    receipt = _append_receipt()
    appended = AuditIntentAppendResult(
        candidate_intent_digest=receipt.intent.intent_digest,
        decision=AuditIntentAppendDecision.APPENDED,
        observed_intent_digest=receipt.intent.intent_digest,
        receipt=receipt,
    )
    duplicate = replace(
        appended,
        decision=AuditIntentAppendDecision.DUPLICATE_SAME,
    )
    conflict = AuditIntentAppendResult(
        candidate_intent_digest=receipt.intent.intent_digest,
        decision=AuditIntentAppendDecision.CONFLICT,
        observed_intent_digest=_DIGEST,
        receipt=None,
    )

    assert appended.receipt is receipt
    assert duplicate.receipt is receipt
    assert conflict.receipt is None
    with pytest.raises(ValueError, match="mismatched candidate"):
        replace(appended, observed_intent_digest=_DIGEST)


def test_audit_intent_rejects_expired_or_nonreserved_reservation() -> None:
    receipt = _reservation_receipt()
    with pytest.raises(ValueError, match="outside the reservation lease"):
        PreEffectAuditIntent.create(
            reservation_receipt=receipt,
            actor="fdai.core.executor",
            created_at=receipt.record.lease_expires_at,
        )

    in_flight_record = begin_dispatch(
        receipt.record,
        at=_NOW + timedelta(seconds=1),
    )
    in_flight_receipt = IdempotencyReservationTransitionReceipt.create(
        prior_record=receipt.record,
        record=in_flight_record,
        expected_prior_revision=receipt.record.revision,
        store_receipt_digest="sha256:" + "7" * 64,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="current reserved"):
        PreEffectAuditIntent.create(
            reservation_receipt=in_flight_receipt,
            actor="fdai.core.executor",
            created_at=_NOW + timedelta(seconds=2),
        )


def test_audit_intent_cannot_predate_reservation_readback() -> None:
    base = _reservation_receipt()
    delayed = IdempotencyReservationTransitionReceipt.create(
        prior_record=None,
        record=base.record,
        expected_prior_revision=0,
        store_receipt_digest=base.store_receipt_digest,
        recorded_at=_NOW + timedelta(seconds=5),
    )
    with pytest.raises(ValueError, match="outside the reservation lease"):
        PreEffectAuditIntent.create(
            reservation_receipt=delayed,
            actor="fdai.core.executor",
            created_at=_NOW + timedelta(seconds=1),
        )


def test_append_receipt_rejects_partial_or_late_readback() -> None:
    intent = _intent()
    with pytest.raises(ValueError, match="chronology"):
        AuditIntentAppendReceipt.create(
            intent=intent,
            persisted_intent_digest=intent.intent_digest,
            store_receipt_digest="sha256:" + "6" * 64,
            persisted_at=_NOW + timedelta(seconds=2),
            read_back_at=intent.reservation_receipt.record.lease_expires_at,
        )
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(_append_receipt(), receipt_digest="sha256:" + "0" * 64)


def test_audit_intent_and_append_replay_are_deterministic() -> None:
    assert _intent() == _intent()
    assert _append_receipt() == _append_receipt()


def test_pre_effect_audit_intent_validation_and_subclass_guards() -> None:
    intent = _intent()
    with pytest.raises(TypeError, match="does not support subclasses"):

        class _SubIntent(PreEffectAuditIntent):
            pass

        _SubIntent.create(
            reservation_receipt=_reservation_receipt(),
            actor="fdai.core.executor",
            created_at=_NOW + timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match="unsupported pre-effect audit intent schema"):
        replace(intent, schema_version="2.0.0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(intent, execution_authority=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(intent, effect_verified=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact reservation receipt"):
        replace(intent, reservation_receipt="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="actor MUST be canonical and bounded"):
        replace(intent, actor=" leading-space")
    with pytest.raises(ValueError, match="phase MUST be pre_effect"):
        replace(intent, audit_phase="post_effect")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="normalized to UTC"):
        replace(
            intent,
            created_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone(timedelta(hours=1))),
        )
    with pytest.raises(ValueError, match="MUST include a timezone"):
        PreEffectAuditIntent.create(
            reservation_receipt=_reservation_receipt(),
            actor="fdai.core.executor",
            created_at=datetime(2026, 9, 10, 9, 0),
        )
    with pytest.raises(ValueError, match="MUST be SHA-256"):
        replace(intent, intent_digest="not-a-digest")
    with pytest.raises(ValueError, match="digest mismatched"):
        replace(intent, intent_digest="sha256:" + "f" * 64)


def test_append_receipt_and_result_validation_guards() -> None:
    receipt = _append_receipt()
    with pytest.raises(TypeError, match="does not support subclasses"):

        class _SubReceipt(AuditIntentAppendReceipt):
            pass

        _SubReceipt.create(
            intent=_intent(),
            persisted_intent_digest=_intent().intent_digest,
            store_receipt_digest="sha256:" + "6" * 64,
            persisted_at=_NOW + timedelta(seconds=2),
            read_back_at=_NOW + timedelta(seconds=3),
        )

    with pytest.raises(ValueError, match="unsupported audit intent append receipt schema"):
        replace(receipt, schema_version="2.0.0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(receipt, execution_authority=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exact intent"):
        replace(receipt, intent="not-an-intent")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="decision is invalid"):
        AuditIntentAppendResult(
            candidate_intent_digest=receipt.intent.intent_digest,
            decision="invalid",  # type: ignore[arg-type]
            observed_intent_digest=receipt.intent.intent_digest,
            receipt=receipt,
        )
    with pytest.raises(ValueError, match="MUST NOT contain success evidence"):
        AuditIntentAppendResult(
            candidate_intent_digest=receipt.intent.intent_digest,
            decision=AuditIntentAppendDecision.CONFLICT,
            observed_intent_digest=receipt.intent.intent_digest,
            receipt=None,
        )
    with pytest.raises(ValueError, match="MUST NOT contain success evidence"):
        AuditIntentAppendResult(
            candidate_intent_digest=receipt.intent.intent_digest,
            decision=AuditIntentAppendDecision.CONFLICT,
            observed_intent_digest=_DIGEST,
            receipt=receipt,
        )


def test_audit_intent_to_mapping_and_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    intent = _intent()
    mapping = audit_intent_to_mapping(intent)
    assert mapping["intent_digest"] == intent.intent_digest
    assert mapping["actor"] == "fdai.core.executor"

    nested = _normalize_digest_value((intent, [AuditIntentAppendDecision.APPENDED]))
    assert isinstance(nested, list)

    with pytest.raises(ValueError, match="requires an exact intent"):
        audit_intent_to_mapping("not-an-intent")  # type: ignore[arg-type]

    monkeypatch.setattr(
        "fdai.core.executor.audit_intent._normalize_digest_value",
        lambda _value: "not-a-dict",
    )
    with pytest.raises(ValueError, match="not an object"):
        audit_intent_to_mapping(intent)
