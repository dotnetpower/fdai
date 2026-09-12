"""Context-bound proof statements for finalizing execution safeguard bundles."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from fdai_service_contracts.execution_safeguards import (
    SafeguardProof,
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor_models import ExecutionPath as ServiceExecutionPath
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.safeguards import (
    SafeguardReceipt,
    action_dry_run_receipt,
    execution_fingerprint,
    full_action_digest,
    resource_lock_key,
)
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    require_current_lock_ownership,
    resource_lock_target_digest,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_HEX_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_REVISION = re.compile(r"^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$")


@dataclass(frozen=True, slots=True)
class LogicalTargetLockProof:
    """Caller-produced proof that the exact target lock was acquired."""

    action_digest: str
    execution_path: ExecutionPath
    execution_fingerprint: str
    lock_key: str
    source_revision: str
    completed_at: datetime
    operation_receipt_digest: str
    proof_digest: str

    @classmethod
    def create(
        cls,
        *,
        action_digest: str,
        execution_path: ExecutionPath,
        execution_fingerprint: str,
        lock_key: str,
        source_revision: str,
        completed_at: datetime,
        operation_receipt_digest: str,
    ) -> Self:
        """Create a content-addressed lock statement."""

        values: dict[str, object] = {
            "action_digest": action_digest,
            "execution_path": execution_path,
            "execution_fingerprint": execution_fingerprint,
            "lock_key": lock_key,
            "source_revision": source_revision,
            "completed_at": completed_at,
            "operation_receipt_digest": operation_receipt_digest,
        }
        return cls(
            action_digest=action_digest,
            execution_path=execution_path,
            execution_fingerprint=execution_fingerprint,
            lock_key=lock_key,
            source_revision=source_revision,
            completed_at=completed_at,
            operation_receipt_digest=operation_receipt_digest,
            proof_digest=_proof_digest("logical_target_lock", values),
        )

    def __post_init__(self) -> None:
        _validate_statement(
            "logical_target_lock",
            self.proof_digest,
            {
                "action_digest": self.action_digest,
                "execution_path": self.execution_path,
                "execution_fingerprint": self.execution_fingerprint,
                "lock_key": self.lock_key,
                "source_revision": self.source_revision,
                "completed_at": self.completed_at,
                "operation_receipt_digest": self.operation_receipt_digest,
            },
        )


@dataclass(frozen=True, slots=True)
class IdempotencyReservationProof:
    """Caller-produced proof of durable duplicate suppression."""

    action_digest: str
    execution_path: ExecutionPath
    execution_fingerprint: str
    idempotency_key: str
    reservation_outcome: Literal["reserved", "duplicate_same"]
    source_revision: str
    completed_at: datetime
    store_receipt_digest: str
    proof_digest: str

    @classmethod
    def create(
        cls,
        *,
        action_digest: str,
        execution_path: ExecutionPath,
        execution_fingerprint: str,
        idempotency_key: str,
        reservation_outcome: Literal["reserved", "duplicate_same"],
        source_revision: str,
        completed_at: datetime,
        store_receipt_digest: str,
    ) -> Self:
        """Create a content-addressed idempotency-reservation statement."""

        values = {
            "action_digest": action_digest,
            "execution_path": execution_path,
            "execution_fingerprint": execution_fingerprint,
            "idempotency_key": idempotency_key,
            "reservation_outcome": reservation_outcome,
            "source_revision": source_revision,
            "completed_at": completed_at,
            "store_receipt_digest": store_receipt_digest,
        }
        return cls(
            action_digest=action_digest,
            execution_path=execution_path,
            execution_fingerprint=execution_fingerprint,
            idempotency_key=idempotency_key,
            reservation_outcome=reservation_outcome,
            source_revision=source_revision,
            completed_at=completed_at,
            store_receipt_digest=store_receipt_digest,
            proof_digest=_proof_digest("idempotency", values),
        )

    def __post_init__(self) -> None:
        if self.reservation_outcome not in {"reserved", "duplicate_same"}:
            raise ValueError("idempotency reservation outcome is not durable success")
        _validate_statement(
            "idempotency",
            self.proof_digest,
            {
                "action_digest": self.action_digest,
                "execution_path": self.execution_path,
                "execution_fingerprint": self.execution_fingerprint,
                "idempotency_key": self.idempotency_key,
                "reservation_outcome": self.reservation_outcome,
                "source_revision": self.source_revision,
                "completed_at": self.completed_at,
                "store_receipt_digest": self.store_receipt_digest,
            },
        )


@dataclass(frozen=True, slots=True)
class AuditIntentProof:
    """Caller-produced proof that pre-effect audit intent was persisted."""

    action_digest: str
    execution_path: ExecutionPath
    execution_fingerprint: str
    audit_entry_digest: str
    source_revision: str
    completed_at: datetime
    append_receipt_digest: str
    proof_digest: str

    @classmethod
    def create(
        cls,
        *,
        action_digest: str,
        execution_path: ExecutionPath,
        execution_fingerprint: str,
        audit_entry_digest: str,
        source_revision: str,
        completed_at: datetime,
        append_receipt_digest: str,
    ) -> Self:
        """Create a content-addressed audit-intent statement."""

        values = {
            "action_digest": action_digest,
            "execution_path": execution_path,
            "execution_fingerprint": execution_fingerprint,
            "audit_entry_digest": audit_entry_digest,
            "source_revision": source_revision,
            "completed_at": completed_at,
            "append_receipt_digest": append_receipt_digest,
        }
        return cls(
            action_digest=action_digest,
            execution_path=execution_path,
            execution_fingerprint=execution_fingerprint,
            audit_entry_digest=audit_entry_digest,
            source_revision=source_revision,
            completed_at=completed_at,
            append_receipt_digest=append_receipt_digest,
            proof_digest=_proof_digest("audit_intent", values),
        )

    def __post_init__(self) -> None:
        _validate_statement(
            "audit_intent",
            self.proof_digest,
            {
                "action_digest": self.action_digest,
                "execution_path": self.execution_path,
                "execution_fingerprint": self.execution_fingerprint,
                "audit_entry_digest": self.audit_entry_digest,
                "source_revision": self.source_revision,
                "completed_at": self.completed_at,
                "append_receipt_digest": self.append_receipt_digest,
            },
        )


def finalize_safeguard_proof_bundle(
    action: Action,
    *,
    receipt: SafeguardReceipt,
    source_revision: str,
    recorded_at: datetime,
    lock_proof: LogicalTargetLockProof,
    lock_assessment: LiveLockOwnershipAssessment,
    expected_lock_verifier_id: str,
    expected_lock_verifier_version: str,
    expected_lock_trust_anchor_id: str,
    idempotency_proof: IdempotencyReservationProof,
    audit_intent_proof: AuditIntentProof,
) -> SafeguardProofBundle:
    """Validate bound operation proofs and return the canonical seven-proof bundle."""

    action_digest = full_action_digest(action)
    expected_fingerprint = execution_fingerprint(
        action=action,
        execution_path=receipt.execution_path,
    )
    if receipt.action_digest != action_digest:
        raise ValueError("safeguard receipt action digest does not match the full action")
    if receipt.execution_fingerprint != expected_fingerprint:
        raise ValueError("safeguard receipt fingerprint does not match the full action")
    if receipt.idempotency_key != action.idempotency_key:
        raise ValueError("safeguard receipt idempotency key does not match the action")
    if receipt.dry_run_receipt != action_dry_run_receipt(
        action,
        execution_path=receipt.execution_path,
        plan_digest=receipt.plan_digest,
        plan_kind=receipt.plan_kind,
    ):
        raise ValueError("safeguard dry-run receipt does not match its canonical plan")
    if _SOURCE_REVISION.fullmatch(source_revision) is None:
        raise ValueError("safeguard proof source revision MUST be a canonical commit revision")
    if (
        action.created_at.tzinfo is None
        or action.created_at.utcoffset() is None
        or recorded_at.tzinfo is None
        or recorded_at.utcoffset() is None
        or action.created_at > recorded_at
    ):
        raise ValueError("safeguard proof recorded_at MUST include a timezone")

    current_lock = require_current_lock_ownership(
        lock_assessment,
        observed_at=recorded_at,
    )
    statements = (lock_proof, idempotency_proof, audit_intent_proof)
    for statement in statements:
        if (
            statement.action_digest != action_digest
            or statement.execution_path is not receipt.execution_path
            or statement.execution_fingerprint != receipt.execution_fingerprint
            or statement.source_revision != source_revision
            or statement.completed_at < action.created_at
            or statement.completed_at > recorded_at
        ):
            raise ValueError("safeguard operation proof does not match the exact action context")
    expected_lock_key = resource_lock_key(action.target_resource_ref)
    if receipt.resource_lock_key != expected_lock_key or lock_proof.lock_key != expected_lock_key:
        raise ValueError("safeguard lock proof does not match the target lock")
    acquisition = current_lock.acquisition_receipt
    if (
        acquisition.lock_key != expected_lock_key
        or acquisition.target_digest != resource_lock_target_digest(action.target_resource_ref)
        or acquisition.action_digest != action_digest
        or acquisition.source_revision != source_revision
        or lock_proof.operation_receipt_digest != acquisition.receipt_digest
    ):
        raise ValueError("safeguard live lock evidence does not match the exact action context")
    if not (
        action.created_at
        <= acquisition.acquired_at
        <= lock_proof.completed_at
        <= current_lock.evaluated_at
        <= recorded_at
    ):
        raise ValueError("safeguard live lock evidence violates causal ordering")
    if (
        current_lock.verifier_id != expected_lock_verifier_id
        or current_lock.verifier_version != expected_lock_verifier_version
        or current_lock.trust_anchor_id != expected_lock_trust_anchor_id
    ):
        raise ValueError("safeguard live lock evidence does not match trusted verifier")
    if idempotency_proof.idempotency_key != receipt.idempotency_key:
        raise ValueError("safeguard idempotency proof does not match the stable key")
    if idempotency_proof.reservation_outcome not in {"reserved", "duplicate_same"}:
        raise ValueError("safeguard idempotency reservation did not suppress duplicates")

    proofs = (
        SafeguardProof(
            kind=SafeguardProofKind.STOP_CONDITION,
            proof_digest=content_digest(
                {
                    "action_digest": action_digest,
                    "stop_conditions": action.model_dump(mode="json")["stop_conditions"],
                }
            ),
        ),
        SafeguardProof(
            kind=SafeguardProofKind.ROLLBACK,
            proof_digest=content_digest(
                {
                    "action_digest": action_digest,
                    "rollback": action.rollback_ref.model_dump(mode="json"),
                }
            ),
        ),
        SafeguardProof(
            kind=SafeguardProofKind.IMPACT_SCOPE,
            proof_digest=content_digest(
                {
                    "action_digest": action_digest,
                    "blast_radius": action.blast_radius.model_dump(mode="json"),
                }
            ),
        ),
        SafeguardProof(
            kind=SafeguardProofKind.DRY_RUN,
            proof_digest=receipt.dry_run_receipt,
        ),
        SafeguardProof(
            kind=SafeguardProofKind.LOGICAL_TARGET_LOCK,
            proof_digest=content_digest(
                {
                    "logical_target_lock_proof_digest": lock_proof.proof_digest,
                    "live_lock_ownership_assessment_digest": (current_lock.assessment_digest),
                }
            ),
        ),
        SafeguardProof(
            kind=SafeguardProofKind.IDEMPOTENCY,
            proof_digest=idempotency_proof.proof_digest,
        ),
        SafeguardProof(
            kind=SafeguardProofKind.AUDIT_INTENT,
            proof_digest=audit_intent_proof.proof_digest,
        ),
    )
    return SafeguardProofBundle.create(
        action_id=action.action_id,
        execution_path=ServiceExecutionPath(receipt.execution_path.value),
        execution_fingerprint=f"sha256:{receipt.execution_fingerprint}",
        source_revision=source_revision,
        recorded_at=recorded_at.astimezone(UTC),
        proofs=proofs,
    )


def _proof_digest(kind: str, values: Mapping[str, object]) -> str:
    payload = dict(values)
    completed_at = payload.get("completed_at")
    if isinstance(completed_at, datetime):
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("safeguard proof completion time MUST include a timezone")
        payload["completed_at"] = completed_at.astimezone(UTC).isoformat()
    payload["kind"] = kind
    return content_digest(payload)


def _validate_statement(
    kind: str,
    proof_digest: str,
    values: Mapping[str, object],
) -> None:
    payload = dict(values)
    if not all(
        isinstance(payload.get(name), str) and str(payload[name]).strip()
        for name in (
            "action_digest",
            "execution_fingerprint",
            "source_revision",
        )
    ):
        raise ValueError("safeguard proof identity fields MUST be non-empty")
    source_revision = str(payload["source_revision"])
    if _SOURCE_REVISION.fullmatch(source_revision) is None:
        raise ValueError("safeguard proof source revision MUST be a canonical commit revision")
    if _DIGEST.fullmatch(str(payload["action_digest"])) is None:
        raise ValueError("safeguard proof action digest MUST be SHA-256")
    if _HEX_DIGEST.fullmatch(str(payload["execution_fingerprint"])) is None:
        raise ValueError("safeguard proof execution fingerprint MUST be lowercase SHA-256")
    evidence_digest_names = {
        "operation_receipt_digest",
        "store_receipt_digest",
        "audit_entry_digest",
        "append_receipt_digest",
    }
    for name in evidence_digest_names & payload.keys():
        if _DIGEST.fullmatch(str(payload[name])) is None:
            raise ValueError(f"safeguard proof {name} MUST be SHA-256")
    if proof_digest != _proof_digest(kind, payload):
        raise ValueError("safeguard operation proof digest mismatched")


__all__ = [
    "AuditIntentProof",
    "IdempotencyReservationProof",
    "LogicalTargetLockProof",
    "finalize_safeguard_proof_bundle",
    "full_action_digest",
]
