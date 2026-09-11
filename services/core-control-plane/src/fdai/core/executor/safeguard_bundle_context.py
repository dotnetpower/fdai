"""Exact reservation, lock, and audit context for bundle persistence."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.execution_safeguards import (
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.audit_intent import AuditIntentAppendReceipt
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationTransitionReceipt,
    ReservationState,
)
from fdai.core.executor.safeguard_pre_bundle import (
    SafeguardPreBundleCommitment,
)
from fdai.core.executor.safeguard_proofs import (
    AuditIntentProof,
    IdempotencyReservationProof,
    LogicalTargetLockProof,
    full_action_digest,
)
from fdai.core.executor.safeguards import (
    SafeguardReceipt,
    dry_run_receipt,
    execution_fingerprint,
    resource_lock_key,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    require_current_lock_ownership,
    resource_lock_target_digest,
)


@dataclass(frozen=True, slots=True)
class SafeguardBundlePersistenceContext:
    """Exact operation receipts and proof statements persisted with one bundle."""

    action: Action
    pre_bundle_commitment: SafeguardPreBundleCommitment
    safeguard_receipt: SafeguardReceipt
    reservation_receipt: IdempotencyReservationTransitionReceipt
    audit_append_receipt: AuditIntentAppendReceipt
    lock_assessment: LiveLockOwnershipAssessment
    lock_proof: LogicalTargetLockProof
    idempotency_proof: IdempotencyReservationProof
    audit_intent_proof: AuditIntentProof

    def __post_init__(self) -> None:
        expected_types = (
            (self.action, Action, "action"),
            (
                self.pre_bundle_commitment,
                SafeguardPreBundleCommitment,
                "pre-bundle commitment",
            ),
            (self.safeguard_receipt, SafeguardReceipt, "safeguard receipt"),
            (
                self.reservation_receipt,
                IdempotencyReservationTransitionReceipt,
                "reservation receipt",
            ),
            (
                self.audit_append_receipt,
                AuditIntentAppendReceipt,
                "audit append receipt",
            ),
            (
                self.lock_assessment,
                LiveLockOwnershipAssessment,
                "lock assessment",
            ),
            (self.lock_proof, LogicalTargetLockProof, "lock proof"),
            (
                self.idempotency_proof,
                IdempotencyReservationProof,
                "idempotency proof",
            ),
            (self.audit_intent_proof, AuditIntentProof, "audit intent proof"),
        )
        for value, expected_type, name in expected_types:
            if type(value) is not expected_type:
                raise ValueError(f"safeguard bundle context requires an exact {name}")

    def validate(
        self,
        *,
        preparing_fence: TargetDispatchFenceRecord,
        bundle: SafeguardProofBundle,
    ) -> None:
        """Validate every operation receipt against one preparing fence and bundle."""

        if (
            type(preparing_fence) is not TargetDispatchFenceRecord
            or preparing_fence.state is not TargetDispatchFenceState.PREPARING
        ):
            raise ValueError("safeguard bundle context requires a preparing fence")
        if type(bundle) is not SafeguardProofBundle:
            raise ValueError("safeguard bundle context requires an exact bundle")
        fence_identity = preparing_fence.identity
        reservation = self.reservation_receipt.record
        action_digest = full_action_digest(self.action)
        expected_lock_key = resource_lock_key(self.action.target_resource_ref)
        expected_target_digest = resource_lock_target_digest(self.action.target_resource_ref)
        expected_fingerprint = execution_fingerprint(
            action=self.action,
            execution_path=reservation.identity.execution_path,
        )
        self.pre_bundle_commitment.require_matches(
            action=self.action,
            execution_path=reservation.identity.execution_path,
            source_revision=reservation.identity.source_revision,
        )
        if self.pre_bundle_commitment.committed_at > reservation.reserved_at:
            raise ValueError("safeguard pre-bundle commitment followed reservation")
        expected_dry_run = dry_run_receipt(
            execution_fingerprint=expected_fingerprint,
            plan_digest=self.safeguard_receipt.plan_digest,
            plan_kind=self.safeguard_receipt.plan_kind,
        )
        if (
            reservation.state is not ReservationState.RESERVED
            or action_digest != reservation.identity.action_digest
            or bundle.action_id != self.action.action_id
            or reservation.identity.identity_digest != fence_identity.reservation_identity_digest
            or reservation.identity.acquisition_receipt.receipt_digest
            != fence_identity.acquisition_receipt_digest
            or reservation.identity.acquisition_receipt.attempt
            != fence_identity.reservation_attempt
            or fence_identity.target_digest != expected_target_digest
        ):
            raise ValueError("safeguard bundle reservation context mismatched fence")
        if (
            self.safeguard_receipt.action_digest != action_digest
            or self.safeguard_receipt.execution_path is not reservation.identity.execution_path
            or self.safeguard_receipt.execution_fingerprint != expected_fingerprint
            or reservation.identity.execution_fingerprint != expected_fingerprint
            or self.safeguard_receipt.idempotency_key != reservation.identity.idempotency_key
            or self.safeguard_receipt.resource_lock_key != expected_lock_key
            or self.safeguard_receipt.dry_run_receipt != expected_dry_run
        ):
            raise ValueError("safeguard receipt context mismatched reservation")
        if self.audit_append_receipt.intent.reservation_receipt != self.reservation_receipt:
            raise ValueError("safeguard bundle audit receipt changed reservation")
        acquisition = self.lock_assessment.acquisition_receipt
        if (
            acquisition.receipt_digest != fence_identity.acquisition_receipt_digest
            or acquisition.lock_key != expected_lock_key
            or acquisition.target_digest != expected_target_digest
            or self.lock_proof.operation_receipt_digest != acquisition.receipt_digest
        ):
            raise ValueError("safeguard bundle lock context mismatched acquisition")
        require_current_lock_ownership(
            self.lock_assessment,
            observed_at=bundle.recorded_at,
        )
        if (
            self.idempotency_proof.store_receipt_digest != self.reservation_receipt.receipt_digest
            or self.audit_intent_proof.append_receipt_digest
            != self.audit_append_receipt.receipt_digest
        ):
            raise ValueError("safeguard bundle operation receipt binding mismatched")
        if (
            self.lock_proof.lock_key != expected_lock_key
            or self.idempotency_proof.idempotency_key != reservation.identity.idempotency_key
            or self.idempotency_proof.reservation_outcome != "reserved"
            or self.audit_intent_proof.audit_entry_digest
            != self.audit_append_receipt.intent.intent_digest
        ):
            raise ValueError("safeguard bundle statement semantics mismatched receipts")
        statements = (
            self.lock_proof,
            self.idempotency_proof,
            self.audit_intent_proof,
        )
        for statement in statements:
            if (
                statement.action_digest != reservation.identity.action_digest
                or statement.execution_path.value != reservation.identity.execution_path.value
                or statement.execution_fingerprint != reservation.identity.execution_fingerprint
                or statement.source_revision != reservation.identity.source_revision
            ):
                raise ValueError("safeguard bundle statement context mismatched reservation")
        expected_proofs = {
            SafeguardProofKind.STOP_CONDITION: content_digest(
                {
                    "action_digest": action_digest,
                    "stop_conditions": self.action.model_dump(mode="json")["stop_conditions"],
                }
            ),
            SafeguardProofKind.ROLLBACK: content_digest(
                {
                    "action_digest": action_digest,
                    "rollback": self.action.rollback_ref.model_dump(mode="json"),
                }
            ),
            SafeguardProofKind.IMPACT_SCOPE: content_digest(
                {
                    "action_digest": action_digest,
                    "blast_radius": self.action.blast_radius.model_dump(mode="json"),
                }
            ),
            SafeguardProofKind.DRY_RUN: expected_dry_run,
            SafeguardProofKind.LOGICAL_TARGET_LOCK: content_digest(
                {
                    "logical_target_lock_proof_digest": (self.lock_proof.proof_digest),
                    "live_lock_ownership_assessment_digest": (
                        self.lock_assessment.assessment_digest
                    ),
                }
            ),
            SafeguardProofKind.IDEMPOTENCY: self.idempotency_proof.proof_digest,
            SafeguardProofKind.AUDIT_INTENT: self.audit_intent_proof.proof_digest,
        }
        actual_proofs = {proof.kind: proof.proof_digest for proof in bundle.proofs}
        if actual_proofs != expected_proofs:
            raise ValueError("safeguard bundle operation proofs mismatched context")
        latest_prerequisite = max(
            preparing_fence.state_changed_at,
            self.pre_bundle_commitment.committed_at,
            self.reservation_receipt.recorded_at,
            self.audit_append_receipt.read_back_at,
            self.lock_assessment.evaluated_at,
            *(statement.completed_at for statement in statements),
        )
        if (
            bundle.recorded_at < latest_prerequisite
            or bundle.recorded_at >= self.lock_assessment.valid_until
            or bundle.recorded_at >= reservation.lease_expires_at
        ):
            raise ValueError("safeguard bundle chronology mismatched operation context")


__all__ = ["SafeguardBundlePersistenceContext"]
