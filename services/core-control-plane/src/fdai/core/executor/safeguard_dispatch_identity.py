"""Exact execution and operation-proof identity for bundle persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, Self

from fdai_service_contracts.execution_safeguards import SafeguardProofBundle

from fdai.core.executor.safeguard_bundle_context import (
    SafeguardBundlePersistenceContext,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    validate_digest,
    validate_text,
    validate_utc,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
)


@dataclass(frozen=True, slots=True)
class SafeguardDispatchEvidenceIdentity:
    """Exact fence, reservation attempt, bundle, audit, policy, and sink identity."""

    schema_version: Literal["1.0.0"]
    action_id: str
    target_digest: str
    target_fence_identity_digest: str
    target_fence_record_digest: str
    target_fence_generation: int
    target_fence_revision: int
    reservation_identity_digest: str
    reservation_attempt: int
    acquisition_receipt_digest: str
    reservation_receipt_digest: str
    reservation_record_digest: str
    reservation_revision: int
    reservation_lease_expires_at: datetime
    audit_append_receipt_digest: str
    lock_assessment_digest: str
    lock_assessment_valid_until: datetime
    lock_proof_digest: str
    idempotency_proof_digest: str
    audit_intent_proof_digest: str
    pre_bundle_commitment_digest: str
    lock_verifier_id: str
    lock_verifier_version: str
    lock_trust_anchor_id: str
    safeguard_bundle_digest: str
    continuity_policy_digest: str
    execution_path: str
    execution_fingerprint: str
    source_revision: str
    client_correlation_id: str
    sink_idempotency_key: str
    identity_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported safeguard dispatch evidence identity schema")
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("safeguard dispatch evidence identity MUST NOT grant authority")
        validate_text("action_id", self.action_id)
        for digest_name, digest_value in (
            ("target_digest", self.target_digest),
            ("target_fence_identity_digest", self.target_fence_identity_digest),
            ("target_fence_record_digest", self.target_fence_record_digest),
            ("reservation_identity_digest", self.reservation_identity_digest),
            ("acquisition_receipt_digest", self.acquisition_receipt_digest),
            ("reservation_receipt_digest", self.reservation_receipt_digest),
            ("reservation_record_digest", self.reservation_record_digest),
            ("audit_append_receipt_digest", self.audit_append_receipt_digest),
            ("lock_assessment_digest", self.lock_assessment_digest),
            ("lock_proof_digest", self.lock_proof_digest),
            ("idempotency_proof_digest", self.idempotency_proof_digest),
            ("audit_intent_proof_digest", self.audit_intent_proof_digest),
            (
                "pre_bundle_commitment_digest",
                self.pre_bundle_commitment_digest,
            ),
            ("safeguard_bundle_digest", self.safeguard_bundle_digest),
            ("continuity_policy_digest", self.continuity_policy_digest),
            ("identity_digest", self.identity_digest),
        ):
            validate_digest(digest_name, digest_value)
        validate_utc(
            "reservation_lease_expires_at",
            self.reservation_lease_expires_at,
        )
        validate_utc(
            "lock_assessment_valid_until",
            self.lock_assessment_valid_until,
        )
        validate_text("lock_verifier_id", self.lock_verifier_id)
        validate_text("lock_verifier_version", self.lock_verifier_version)
        validate_text("lock_trust_anchor_id", self.lock_trust_anchor_id)
        validate_text("execution_path", self.execution_path)
        validate_digest("execution_fingerprint", self.execution_fingerprint)
        validate_text("source_revision", self.source_revision)
        for integer_name, integer_value in (
            ("target_fence_generation", self.target_fence_generation),
            ("target_fence_revision", self.target_fence_revision),
            ("reservation_attempt", self.reservation_attempt),
            ("reservation_revision", self.reservation_revision),
        ):
            if type(integer_value) is not int or integer_value < 1:
                raise ValueError(f"safeguard dispatch evidence {integer_name} MUST be positive")
        validate_text("client_correlation_id", self.client_correlation_id)
        validate_text("sink_idempotency_key", self.sink_idempotency_key)
        expected_digest = payload_digest(
            asdict(self),
            "safeguard-dispatch-evidence-identity",
            digest_field="identity_digest",
        )
        if self.identity_digest != expected_digest:
            raise ValueError("safeguard dispatch evidence identity digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        preparing_fence: TargetDispatchFenceRecord,
        persistence_context: SafeguardBundlePersistenceContext,
        bundle: SafeguardProofBundle,
    ) -> Self:
        """Create identity from an exact preparing fence and operation context."""

        if cls is not SafeguardDispatchEvidenceIdentity:
            raise TypeError("safeguard dispatch evidence identity does not support subclasses")
        if (
            type(preparing_fence) is not TargetDispatchFenceRecord
            or preparing_fence.state is not TargetDispatchFenceState.PREPARING
            or preparing_fence.audit_append_receipt_digest is not None
            or preparing_fence.safeguard_bundle_digest is not None
        ):
            raise ValueError("safeguard dispatch evidence requires an exact preparing fence")
        if type(persistence_context) is not SafeguardBundlePersistenceContext:
            raise ValueError("safeguard dispatch evidence requires exact persistence context")
        if type(bundle) is not SafeguardProofBundle:
            raise ValueError("safeguard dispatch evidence requires an exact bundle")
        persistence_context.validate(
            preparing_fence=preparing_fence,
            bundle=bundle,
        )
        fence_identity = preparing_fence.identity
        reservation = persistence_context.reservation_receipt.record
        reservation_identity = reservation.identity
        if (
            bundle.execution_path.value != reservation_identity.execution_path.value
            or bundle.execution_fingerprint
            != f"sha256:{reservation_identity.execution_fingerprint}"
            or bundle.source_revision != reservation_identity.source_revision
        ):
            raise ValueError("safeguard dispatch bundle changed execution context")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "action_id": str(persistence_context.action.action_id),
            "target_digest": fence_identity.target_digest,
            "target_fence_identity_digest": fence_identity.identity_digest,
            "target_fence_record_digest": preparing_fence.record_digest,
            "target_fence_generation": fence_identity.generation,
            "target_fence_revision": preparing_fence.revision,
            "reservation_identity_digest": (fence_identity.reservation_identity_digest),
            "reservation_attempt": fence_identity.reservation_attempt,
            "acquisition_receipt_digest": (fence_identity.acquisition_receipt_digest),
            "reservation_receipt_digest": (persistence_context.reservation_receipt.receipt_digest),
            "reservation_record_digest": reservation.record_digest,
            "reservation_revision": reservation.revision,
            "reservation_lease_expires_at": reservation.lease_expires_at,
            "audit_append_receipt_digest": (
                persistence_context.audit_append_receipt.receipt_digest
            ),
            "lock_assessment_digest": (persistence_context.lock_assessment.assessment_digest),
            "lock_assessment_valid_until": (persistence_context.lock_assessment.valid_until),
            "lock_proof_digest": persistence_context.lock_proof.proof_digest,
            "idempotency_proof_digest": (persistence_context.idempotency_proof.proof_digest),
            "audit_intent_proof_digest": (persistence_context.audit_intent_proof.proof_digest),
            "pre_bundle_commitment_digest": (
                persistence_context.pre_bundle_commitment.commitment_digest
            ),
            "lock_verifier_id": persistence_context.lock_assessment.verifier_id,
            "lock_verifier_version": (persistence_context.lock_assessment.verifier_version),
            "lock_trust_anchor_id": (persistence_context.lock_assessment.trust_anchor_id),
            "safeguard_bundle_digest": bundle.bundle_digest,
            "continuity_policy_digest": (fence_identity.continuity_policy_digest),
            "execution_path": reservation_identity.execution_path.value,
            "execution_fingerprint": bundle.execution_fingerprint,
            "source_revision": reservation_identity.source_revision,
            "client_correlation_id": fence_identity.client_correlation_id,
            "sink_idempotency_key": fence_identity.sink_idempotency_key,
            "execution_authority": False,
            "effect_verification_authority": False,
        }
        values["identity_digest"] = payload_digest(
            values,
            "safeguard-dispatch-evidence-identity",
            digest_field="identity_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


__all__ = ["SafeguardDispatchEvidenceIdentity"]
