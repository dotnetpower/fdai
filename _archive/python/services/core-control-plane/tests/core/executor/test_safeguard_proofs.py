"""Context-bound execution safeguard proof finalization tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal, cast
from uuid import UUID

import pytest
from fdai.core.executor.safeguard_proofs import (
    AuditIntentProof,
    IdempotencyReservationProof,
    LogicalTargetLockProof,
    finalize_safeguard_proof_bundle,
    full_action_digest,
)
from fdai.core.executor.safeguards import SafeguardReceipt, evaluate_pre_dispatch
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ExecutionPath,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    resource_lock_target_digest,
)
from fdai_service_contracts.execution_safeguards import SafeguardProofKind

_NOW = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40
_LOCK_VERIFIER_ID = "postgres-lock-readback"
_LOCK_VERIFIER_VERSION = "1.0.0"
_LOCK_TRUST_ANCHOR_ID = "postgres:primary"


def _action(**overrides: object) -> Action:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "action_id": UUID(int=1),
        "idempotency_key": "example-idem",
        "event_id": UUID(int=2),
        "action_type": "ops.restart-service",
        "target_resource_ref": "resource/example",
        "operation": Operation.RESTART,
        "params": {"name": "example"},
        "stop_condition": StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        "stop_conditions": [
            ActionStopCondition(
                kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS,
                seconds=60,
            )
        ],
        "rollback_ref": RollbackRef(
            kind=RollbackKind.SCRIPTED,
            reference="rollback/example",
        ),
        "blast_radius": BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        "mode": Mode.SHADOW,
        "citing_rules": ["rule.example"],
        "created_at": _NOW,
    }
    values.update(overrides)
    return Action.model_validate(values)


def _receipt(action: Action, path: ExecutionPath = ExecutionPath.DIRECT_API) -> SafeguardReceipt:
    receipt = evaluate_pre_dispatch(
        action,
        execution_path=path,
        plan_digest="plan-digest",
        plan_kind="test-plan",
    )
    assert isinstance(receipt, SafeguardReceipt)
    return receipt


def _lock_acquisition(
    action: Action,
    receipt: SafeguardReceipt,
    **overrides: object,
) -> ResourceLockAcquisitionReceipt:
    request = ResourceLockAcquisitionRequest.create(
        target_ref=action.target_resource_ref,
        action_digest=full_action_digest(action),
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision=_SOURCE_REVISION,
    )
    values: dict[str, object] = {
        "lock_key": receipt.resource_lock_key,
        "target_digest": resource_lock_target_digest(action.target_resource_ref),
        "action_digest": full_action_digest(action),
        "attempt": 1,
        "provider_id": "postgres-advisory-lock",
        "provider_version": "1.0.0",
        "producer_id": "fdai.core.executor",
        "producer_version": "1.0.0",
        "owner_token_digest": "sha256:" + "0" * 64,
        "fencing_generation": 4,
        "session_identity": None,
        "provider_attestation_digest": "sha256:" + "5" * 64,
        "trust_anchor_id": _LOCK_TRUST_ANCHOR_ID,
        "acquired_at": _NOW,
        "valid_until": _NOW + timedelta(minutes=1),
        "source_revision": _SOURCE_REVISION,
        "request_digest": request.request_digest,
    }
    values.update(overrides)
    return ResourceLockAcquisitionReceipt.create(**values)


def _lock_assessment(
    acquisition: ResourceLockAcquisitionReceipt,
    **overrides: object,
) -> LiveLockOwnershipAssessment:
    values: dict[str, object] = {
        "current_fencing_generation": 4,
        "current_session_identity": None,
        "verifier_id": _LOCK_VERIFIER_ID,
        "verifier_version": _LOCK_VERIFIER_VERSION,
        "trust_anchor_id": _LOCK_TRUST_ANCHOR_ID,
        "provider_attestation_digest": "sha256:" + "6" * 64,
        "evaluated_at": _NOW,
        "valid_until": _NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return LiveLockOwnershipAssessment.create(
        acquisition,
        **values,  # type: ignore[arg-type]
    )


def _proofs(
    action: Action,
    receipt: SafeguardReceipt,
):
    acquisition = _lock_acquisition(action, receipt)
    lock_assessment = _lock_assessment(acquisition)
    context = {
        "action_digest": full_action_digest(action),
        "execution_path": receipt.execution_path,
        "execution_fingerprint": receipt.execution_fingerprint,
        "source_revision": _SOURCE_REVISION,
        "completed_at": _NOW,
    }
    return (
        LogicalTargetLockProof.create(
            **context,
            lock_key=receipt.resource_lock_key,
            operation_receipt_digest=acquisition.receipt_digest,
        ),
        IdempotencyReservationProof.create(
            **context,
            idempotency_key=receipt.idempotency_key,
            reservation_outcome="reserved",
            store_receipt_digest="sha256:" + "2" * 64,
        ),
        AuditIntentProof.create(
            **context,
            audit_entry_digest="sha256:" + "3" * 64,
            append_receipt_digest="sha256:" + "4" * 64,
        ),
        lock_assessment,
    )


@pytest.mark.parametrize("path", list(ExecutionPath))
def test_finalizer_emits_canonical_no_authority_bundle(path: ExecutionPath) -> None:
    action = _action()
    receipt = _receipt(action, path)
    lock, idempotency, audit, lock_assessment = _proofs(action, receipt)

    bundle = finalize_safeguard_proof_bundle(
        action,
        receipt=receipt,
        source_revision=_SOURCE_REVISION,
        recorded_at=_NOW,
        lock_proof=lock,
        lock_assessment=lock_assessment,
        expected_lock_verifier_id=_LOCK_VERIFIER_ID,
        expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
        expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
        idempotency_proof=idempotency,
        audit_intent_proof=audit,
    )

    assert bundle.execution_path.value == path.value
    assert bundle.effect_verified is False
    assert bundle.execution_authority is False
    assert bundle.approval_authority is False
    assert bundle.promotion_authority is False
    assert len(bundle.proofs) == 7


def test_full_action_digest_covers_structured_and_lineage_fields() -> None:
    action = _action()
    changed_stop = action.model_copy(
        update={
            "stop_conditions": [
                ActionStopCondition(
                    kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS,
                    seconds=120,
                )
            ]
        }
    )
    changed_time = action.model_copy(update={"created_at": _NOW + timedelta(seconds=1)})

    assert full_action_digest(changed_stop) != full_action_digest(action)
    assert full_action_digest(changed_time) != full_action_digest(action)


@pytest.mark.parametrize("path", list(ExecutionPath))
def test_dry_run_artifact_identity_does_not_replace_full_action_binding(
    path: ExecutionPath,
) -> None:
    action = _action()
    original = _receipt(action, path)
    later = _receipt(_action(created_at=_NOW + timedelta(seconds=1)), path)
    changed_plan = _receipt(_action(params={"name": "other"}), path)
    changed_guard = _receipt(
        _action(
            stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
            stop_conditions=[
                ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
            ],
        ),
        path,
    )

    assert later.dry_run_receipt == original.dry_run_receipt
    assert later.execution_fingerprint != original.execution_fingerprint
    assert later.action_digest != original.action_digest
    for changed in (changed_plan, changed_guard):
        assert changed.dry_run_receipt != original.dry_run_receipt
        assert changed.execution_fingerprint != original.execution_fingerprint


def test_stable_dry_run_artifact_cannot_authorize_a_changed_action() -> None:
    action = _action()
    receipt = _receipt(action)
    changed = _action(created_at=_NOW + timedelta(seconds=1))
    assert _receipt(changed).dry_run_receipt == receipt.dry_run_receipt
    lock, idempotency, audit, assessment = _proofs(action, receipt)

    with pytest.raises(ValueError, match="action digest"):
        finalize_safeguard_proof_bundle(
            changed,
            receipt=receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW + timedelta(seconds=1),
            lock_proof=lock,
            lock_assessment=assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )


def test_finalizer_rejects_cross_action_path_lock_and_audit_proofs() -> None:
    action = _action()
    receipt = _receipt(action)
    lock, idempotency, audit, lock_assessment = _proofs(action, receipt)

    with pytest.raises(ValueError, match="action digest"):
        finalize_safeguard_proof_bundle(
            _action(params={"name": "other"}),
            receipt=receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW,
            lock_proof=lock,
            lock_assessment=lock_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )
    with pytest.raises(ValueError, match="target lock"):
        finalize_safeguard_proof_bundle(
            action,
            receipt=receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW,
            lock_proof=replace(
                lock,
                lock_key="fdai:resource:other",
                proof_digest=LogicalTargetLockProof.create(
                    action_digest=lock.action_digest,
                    execution_path=lock.execution_path,
                    execution_fingerprint=lock.execution_fingerprint,
                    lock_key="fdai:resource:other",
                    source_revision=lock.source_revision,
                    completed_at=lock.completed_at,
                    operation_receipt_digest=lock.operation_receipt_digest,
                ).proof_digest,
            ),
            lock_assessment=lock_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )
    wrong_receipt = replace(
        receipt,
        resource_lock_key="fdai:resource:other",
    )
    wrong_lock = LogicalTargetLockProof.create(
        action_digest=lock.action_digest,
        execution_path=lock.execution_path,
        execution_fingerprint=lock.execution_fingerprint,
        lock_key=wrong_receipt.resource_lock_key,
        source_revision=lock.source_revision,
        completed_at=lock.completed_at,
        operation_receipt_digest=lock.operation_receipt_digest,
    )
    with pytest.raises(ValueError, match="target lock"):
        finalize_safeguard_proof_bundle(
            action,
            receipt=wrong_receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW,
            lock_proof=wrong_lock,
            lock_assessment=lock_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )
    with pytest.raises(ValueError, match="completion time"):
        AuditIntentProof.create(
            action_digest=full_action_digest(action),
            execution_path=receipt.execution_path,
            execution_fingerprint=receipt.execution_fingerprint,
            audit_entry_digest="sha256:" + "3" * 64,
            source_revision=_SOURCE_REVISION,
            completed_at=datetime(2026, 9, 10),
            append_receipt_digest="sha256:" + "4" * 64,
        )


def test_proof_and_bundle_tampering_fail_closed() -> None:
    action = _action()
    receipt = _receipt(action)
    lock, idempotency, audit, lock_assessment = _proofs(action, receipt)

    with pytest.raises(ValueError, match="digest mismatched"):
        replace(lock, proof_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="dry-run receipt"):
        finalize_safeguard_proof_bundle(
            action,
            receipt=replace(receipt, dry_run_receipt="sha256:" + "f" * 64),
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW,
            lock_proof=lock,
            lock_assessment=lock_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )
    with pytest.raises(ValueError, match="operation_receipt_digest"):
        LogicalTargetLockProof.create(
            action_digest=lock.action_digest,
            execution_path=lock.execution_path,
            execution_fingerprint=lock.execution_fingerprint,
            lock_key=lock.lock_key,
            source_revision=lock.source_revision,
            completed_at=lock.completed_at,
            operation_receipt_digest="",
        )
    with pytest.raises(ValueError, match="durable success"):
        IdempotencyReservationProof(
            action_digest=idempotency.action_digest,
            execution_path=idempotency.execution_path,
            execution_fingerprint=idempotency.execution_fingerprint,
            idempotency_key=idempotency.idempotency_key,
            reservation_outcome=cast(Literal["reserved", "duplicate_same"], "failed"),
            source_revision=idempotency.source_revision,
            completed_at=idempotency.completed_at,
            store_receipt_digest=idempotency.store_receipt_digest,
            proof_digest=idempotency.proof_digest,
        )
    with pytest.raises(ValueError, match="source revision"):
        AuditIntentProof.create(
            action_digest=audit.action_digest,
            execution_path=audit.execution_path,
            execution_fingerprint=audit.execution_fingerprint,
            audit_entry_digest=audit.audit_entry_digest,
            source_revision=f" {_SOURCE_REVISION} ",
            completed_at=audit.completed_at,
            append_receipt_digest=audit.append_receipt_digest,
        )
    with pytest.raises(ValueError, match="recorded_at"):
        finalize_safeguard_proof_bundle(
            action,
            receipt=receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW - timedelta(seconds=1),
            lock_proof=lock,
            lock_assessment=lock_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )
    future_action = action.model_copy(update={"created_at": _NOW + timedelta(seconds=1)})
    future_receipt = _receipt(future_action)
    future_lock, future_idempotency, future_audit, future_lock_assessment = _proofs(
        future_action, future_receipt
    )
    with pytest.raises(ValueError, match="recorded_at"):
        finalize_safeguard_proof_bundle(
            future_action,
            receipt=future_receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW,
            lock_proof=future_lock,
            lock_assessment=future_lock_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=future_idempotency,
            audit_intent_proof=future_audit,
        )

    offset = timezone(timedelta(hours=9))
    bundle = finalize_safeguard_proof_bundle(
        action,
        receipt=receipt,
        source_revision=_SOURCE_REVISION,
        recorded_at=_NOW.astimezone(offset),
        lock_proof=lock,
        lock_assessment=lock_assessment,
        expected_lock_verifier_id=_LOCK_VERIFIER_ID,
        expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
        expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
        idempotency_proof=idempotency,
        audit_intent_proof=audit,
    )
    assert bundle.recorded_at == _NOW


def test_finalizer_rejects_historical_stale_lost_expired_and_wrong_fence() -> None:
    action = _action()
    receipt = _receipt(action)
    lock, idempotency, audit, assessment = _proofs(action, receipt)
    common = {
        "receipt": receipt,
        "source_revision": _SOURCE_REVISION,
        "recorded_at": _NOW,
        "lock_proof": lock,
        "expected_lock_verifier_id": _LOCK_VERIFIER_ID,
        "expected_lock_verifier_version": _LOCK_VERIFIER_VERSION,
        "expected_lock_trust_anchor_id": _LOCK_TRUST_ANCHOR_ID,
        "idempotency_proof": idempotency,
        "audit_intent_proof": audit,
    }

    with pytest.raises(ValueError, match="historical lock acquisition"):
        finalize_safeguard_proof_bundle(
            action,
            **common,
            lock_assessment=cast(LiveLockOwnershipAssessment, assessment.acquisition_receipt),
        )

    stale = _lock_assessment(
        assessment.acquisition_receipt,
        valid_until=_NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="is stale"):
        finalize_safeguard_proof_bundle(
            action,
            **{**common, "recorded_at": stale.valid_until},
            lock_assessment=stale,
        )

    lost = _lock_assessment(
        assessment.acquisition_receipt,
        rejection_reasons=(LockOwnershipRejectionReason.LOCK_LOST,),
    )
    with pytest.raises(ValueError, match="is ineligible"):
        finalize_safeguard_proof_bundle(action, **common, lock_assessment=lost)

    expired_acquisition = _lock_acquisition(
        action,
        receipt,
        acquired_at=_NOW - timedelta(seconds=2),
        valid_until=_NOW,
    )
    expired = _lock_assessment(
        expired_acquisition,
        evaluated_at=_NOW,
        valid_until=_NOW + timedelta(seconds=1),
    )
    expired_lock = LogicalTargetLockProof.create(
        action_digest=lock.action_digest,
        execution_path=lock.execution_path,
        execution_fingerprint=lock.execution_fingerprint,
        lock_key=lock.lock_key,
        source_revision=lock.source_revision,
        completed_at=lock.completed_at,
        operation_receipt_digest=expired_acquisition.receipt_digest,
    )
    with pytest.raises(ValueError, match="is ineligible"):
        finalize_safeguard_proof_bundle(
            action,
            **{**common, "lock_proof": expired_lock},
            lock_assessment=expired,
        )

    wrong_fence = _lock_assessment(
        assessment.acquisition_receipt,
        current_fencing_generation=5,
    )
    with pytest.raises(ValueError, match="is ineligible"):
        finalize_safeguard_proof_bundle(
            action,
            **common,
            lock_assessment=wrong_fence,
        )


def test_finalizer_rejects_untrusted_verifier_anchor_and_receipt_substitution() -> None:
    action = _action()
    receipt = _receipt(action)
    lock, idempotency, audit, assessment = _proofs(action, receipt)
    common = {
        "receipt": receipt,
        "source_revision": _SOURCE_REVISION,
        "recorded_at": _NOW,
        "lock_proof": lock,
        "lock_assessment": assessment,
        "expected_lock_verifier_id": _LOCK_VERIFIER_ID,
        "expected_lock_verifier_version": _LOCK_VERIFIER_VERSION,
        "expected_lock_trust_anchor_id": _LOCK_TRUST_ANCHOR_ID,
        "idempotency_proof": idempotency,
        "audit_intent_proof": audit,
    }

    with pytest.raises(ValueError, match="trusted verifier"):
        finalize_safeguard_proof_bundle(
            action,
            **{**common, "expected_lock_verifier_id": "untrusted-verifier"},
        )
    with pytest.raises(ValueError, match="trusted verifier"):
        finalize_safeguard_proof_bundle(
            action,
            **{**common, "expected_lock_verifier_version": "9.9.9"},
        )
    with pytest.raises(ValueError, match="trusted verifier"):
        finalize_safeguard_proof_bundle(
            action,
            **{**common, "expected_lock_trust_anchor_id": "postgres:other"},
        )

    substituted_lock = LogicalTargetLockProof.create(
        action_digest=lock.action_digest,
        execution_path=lock.execution_path,
        execution_fingerprint=lock.execution_fingerprint,
        lock_key=lock.lock_key,
        source_revision=lock.source_revision,
        completed_at=lock.completed_at,
        operation_receipt_digest="sha256:" + "f" * 64,
    )
    with pytest.raises(ValueError, match="exact action context"):
        finalize_safeguard_proof_bundle(
            action,
            **{**common, "lock_proof": substituted_lock},
        )


def test_finalizer_rejects_noncausal_lock_evidence() -> None:
    action = _action()
    receipt = _receipt(action)
    lock, idempotency, audit, _assessment = _proofs(action, receipt)

    early_acquisition = _lock_acquisition(
        action,
        receipt,
        acquired_at=_NOW - timedelta(microseconds=1),
    )
    early_assessment = _lock_assessment(early_acquisition)
    early_lock = LogicalTargetLockProof.create(
        action_digest=lock.action_digest,
        execution_path=lock.execution_path,
        execution_fingerprint=lock.execution_fingerprint,
        lock_key=lock.lock_key,
        source_revision=lock.source_revision,
        completed_at=lock.completed_at,
        operation_receipt_digest=early_acquisition.receipt_digest,
    )
    with pytest.raises(ValueError, match="causal ordering"):
        finalize_safeguard_proof_bundle(
            action,
            receipt=receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW,
            lock_proof=early_lock,
            lock_assessment=early_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )


def test_bundle_binds_lock_statement_and_live_assessment_digests() -> None:
    action = _action()
    receipt = _receipt(action)
    lock, idempotency, audit, assessment = _proofs(action, receipt)
    evaluated_at = _NOW + timedelta(seconds=1)
    later_assessment = _lock_assessment(
        assessment.acquisition_receipt,
        evaluated_at=evaluated_at,
        valid_until=evaluated_at + timedelta(seconds=1),
    )
    later_lock = LogicalTargetLockProof.create(
        action_digest=lock.action_digest,
        execution_path=lock.execution_path,
        execution_fingerprint=lock.execution_fingerprint,
        lock_key=lock.lock_key,
        source_revision=lock.source_revision,
        completed_at=_NOW + timedelta(microseconds=1),
        operation_receipt_digest=lock.operation_receipt_digest,
    )
    common = {
        "receipt": receipt,
        "source_revision": _SOURCE_REVISION,
        "recorded_at": evaluated_at,
        "lock_assessment": later_assessment,
        "expected_lock_verifier_id": _LOCK_VERIFIER_ID,
        "expected_lock_verifier_version": _LOCK_VERIFIER_VERSION,
        "expected_lock_trust_anchor_id": _LOCK_TRUST_ANCHOR_ID,
        "idempotency_proof": idempotency,
        "audit_intent_proof": audit,
    }

    first = finalize_safeguard_proof_bundle(
        action,
        **common,
        lock_proof=lock,
    )
    second = finalize_safeguard_proof_bundle(
        action,
        **common,
        lock_proof=later_lock,
    )

    first_lock = next(
        proof for proof in first.proofs if proof.kind is SafeguardProofKind.LOGICAL_TARGET_LOCK
    )
    second_lock = next(
        proof for proof in second.proofs if proof.kind is SafeguardProofKind.LOGICAL_TARGET_LOCK
    )
    assert first_lock.proof_digest != second_lock.proof_digest
    assert first.bundle_digest != second.bundle_digest

    later_acquisition = _lock_acquisition(
        action,
        receipt,
        acquired_at=_NOW + timedelta(seconds=1),
    )
    later_assessment = _lock_assessment(
        later_acquisition,
        evaluated_at=_NOW + timedelta(seconds=1),
        valid_until=_NOW + timedelta(seconds=2),
    )
    later_lock = LogicalTargetLockProof.create(
        action_digest=lock.action_digest,
        execution_path=lock.execution_path,
        execution_fingerprint=lock.execution_fingerprint,
        lock_key=lock.lock_key,
        source_revision=lock.source_revision,
        completed_at=_NOW,
        operation_receipt_digest=later_acquisition.receipt_digest,
    )
    with pytest.raises(ValueError, match="causal ordering"):
        finalize_safeguard_proof_bundle(
            action,
            receipt=receipt,
            source_revision=_SOURCE_REVISION,
            recorded_at=_NOW + timedelta(seconds=1),
            lock_proof=later_lock,
            lock_assessment=later_assessment,
            expected_lock_verifier_id=_LOCK_VERIFIER_ID,
            expected_lock_verifier_version=_LOCK_VERIFIER_VERSION,
            expected_lock_trust_anchor_id=_LOCK_TRUST_ANCHOR_ID,
            idempotency_proof=idempotency,
            audit_intent_proof=audit,
        )
