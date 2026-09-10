"""Durable recovery attempt dispatch after failed compensation (#652).

Persist one distinct recovery attempt, bind it to separate human approval
and action-bound safeguard evidence, and dispatch once through the selected
safeguarded execution path.  A failed immutable compensation proposal is
never reused as the recovery proposal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_POSITIVE_INT = re.compile(r"^[1-9]\d*$")


# ---------------------------------------------------------------------------
# Rejection reasons
# ---------------------------------------------------------------------------


class RecoveryAttemptRejectionReason:
    """Why a recovery attempt cannot proceed."""

    COMPENSATION_NOT_FAILED = "compensation_not_failed"
    HOLD_NOT_ACTIVE = "hold_not_active"
    HOLD_REVISION_MISMATCH = "hold_revision_mismatch"
    PROCESS_TERMINAL = "process_terminal"
    IDENTITY_INVALID = "identity_invalid"
    DUPLICATE_ATTEMPT = "duplicate_attempt"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_REJECTED = "approval_rejected"
    SAFEGUARD_DENIED = "safeguard_denied"
    CLAIM_CONFLICT = "claim_conflict"
    STALE_HOLD = "stale_hold"
    PROPOSAL_REUSE = "proposal_reuse"
    PROVIDER_RECEIPT_MISSING = "provider_receipt_missing"
    CRASH_RECOVERY_NEEDED = "crash_recovery_needed"
    IN_DOUBT = "in_doubt"
    NOT_INVOKED = "not_invoked"


# ---------------------------------------------------------------------------
# Attempt identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveryAttemptIdentity:
    """Deterministic binding of process, compensation, hold, and recovery action."""

    process_id: str
    failed_compensation_proposal_digest: str
    hold_revision: int
    recovery_action_type: str
    recovery_payload_digest: str
    target_digest: str
    source_revision: str
    attempt_number: int
    identity_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("recovery attempt identity MUST NOT grant execution authority")
        if not self.process_id or not self.process_id.strip():
            raise ValueError("recovery attempt identity requires a process_id")
        if _DIGEST.fullmatch(self.failed_compensation_proposal_digest) is None:
            raise ValueError("recovery attempt requires a valid compensation proposal digest")
        if not isinstance(self.hold_revision, int) or self.hold_revision < 1:
            raise ValueError("recovery attempt hold_revision MUST be positive")
        if not self.recovery_action_type or not self.recovery_action_type.strip():
            raise ValueError("recovery attempt requires a recovery_action_type")
        if _DIGEST.fullmatch(self.recovery_payload_digest) is None:
            raise ValueError("recovery attempt requires a valid recovery_payload_digest")
        if _DIGEST.fullmatch(self.target_digest) is None:
            raise ValueError("recovery attempt requires a valid target_digest")
        if not self.source_revision or not self.source_revision.strip():
            raise ValueError("recovery attempt requires a source_revision")
        if not isinstance(self.attempt_number, int) or self.attempt_number < 1:
            raise ValueError("recovery attempt attempt_number MUST be positive")
        if _DIGEST.fullmatch(self.identity_digest) is None:
            raise ValueError("recovery attempt requires a valid identity_digest")
        expected = _attempt_identity_digest(
            process_id=self.process_id,
            failed_compensation_proposal_digest=self.failed_compensation_proposal_digest,
            hold_revision=self.hold_revision,
            recovery_action_type=self.recovery_action_type,
            recovery_payload_digest=self.recovery_payload_digest,
            target_digest=self.target_digest,
            source_revision=self.source_revision,
            attempt_number=self.attempt_number,
        )
        if self.identity_digest != expected:
            raise ValueError("recovery attempt identity digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        process_id: str,
        failed_compensation_proposal_digest: str,
        hold_revision: int,
        recovery_action_type: str,
        recovery_payload_digest: str,
        target_digest: str,
        source_revision: str,
        attempt_number: int,
    ) -> RecoveryAttemptIdentity:
        digest = _attempt_identity_digest(
            process_id=process_id,
            failed_compensation_proposal_digest=failed_compensation_proposal_digest,
            hold_revision=hold_revision,
            recovery_action_type=recovery_action_type,
            recovery_payload_digest=recovery_payload_digest,
            target_digest=target_digest,
            source_revision=source_revision,
            attempt_number=attempt_number,
        )
        return cls(
            process_id=process_id,
            failed_compensation_proposal_digest=failed_compensation_proposal_digest,
            hold_revision=hold_revision,
            recovery_action_type=recovery_action_type,
            recovery_payload_digest=recovery_payload_digest,
            target_digest=target_digest,
            source_revision=source_revision,
            attempt_number=attempt_number,
            identity_digest=digest,
        )


# ---------------------------------------------------------------------------
# Pre-dispatch claim
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveryPreDispatchClaim:
    """Exclusive claim that transitions the attempt revision under the target lock."""

    attempt_identity_digest: str
    hold_revision: int
    claim_revision: int
    idempotency_key: str
    claimed_at: datetime
    claim_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("pre-dispatch claim MUST NOT grant execution authority")
        if _DIGEST.fullmatch(self.attempt_identity_digest) is None:
            raise ValueError("pre-dispatch claim requires a valid attempt_identity_digest")
        if not isinstance(self.hold_revision, int) or self.hold_revision < 1:
            raise ValueError("pre-dispatch claim hold_revision MUST be positive")
        if not isinstance(self.claim_revision, int) or self.claim_revision < 1:
            raise ValueError("pre-dispatch claim revision MUST be positive")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("pre-dispatch claim requires an idempotency_key")
        if self.claimed_at.tzinfo is None or self.claimed_at.utcoffset() is None:
            raise ValueError("pre-dispatch claim requires timezone-aware claimed_at")
        expected = _claim_digest(
            attempt_identity_digest=self.attempt_identity_digest,
            hold_revision=self.hold_revision,
            claim_revision=self.claim_revision,
            idempotency_key=self.idempotency_key,
            claimed_at=self.claimed_at,
        )
        if self.claim_digest != expected:
            raise ValueError("pre-dispatch claim digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        attempt_identity_digest: str,
        hold_revision: int,
        claim_revision: int,
        idempotency_key: str,
        claimed_at: datetime,
    ) -> RecoveryPreDispatchClaim:
        digest = _claim_digest(
            attempt_identity_digest=attempt_identity_digest,
            hold_revision=hold_revision,
            claim_revision=claim_revision,
            idempotency_key=idempotency_key,
            claimed_at=claimed_at,
        )
        return cls(
            attempt_identity_digest=attempt_identity_digest,
            hold_revision=hold_revision,
            claim_revision=claim_revision,
            idempotency_key=idempotency_key,
            claimed_at=claimed_at,
            claim_digest=digest,
        )


# ---------------------------------------------------------------------------
# Dispatch outcome
# ---------------------------------------------------------------------------


class RecoveryDispatchOutcome:
    """Terminal outcome of one recovery dispatch attempt."""

    NOT_INVOKED = "not_invoked"
    DISPATCHED = "dispatched"
    IN_DOUBT = "in_doubt"


@dataclass(frozen=True, slots=True)
class RecoveryDispatchResult:
    """Immutable result after recovery dispatch or fenced non-invocation."""

    attempt_identity_digest: str
    claim_digest: str
    outcome: str
    provider_receipt_digest: str | None
    recorded_at: datetime
    result_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("recovery dispatch result MUST NOT grant execution authority")
        if _DIGEST.fullmatch(self.attempt_identity_digest) is None:
            raise ValueError("dispatch result requires a valid attempt_identity_digest")
        if _DIGEST.fullmatch(self.claim_digest) is None:
            raise ValueError("dispatch result requires a valid claim_digest")
        if self.outcome not in {
            RecoveryDispatchOutcome.NOT_INVOKED,
            RecoveryDispatchOutcome.DISPATCHED,
            RecoveryDispatchOutcome.IN_DOUBT,
        }:
            raise ValueError("dispatch result outcome is invalid")
        if (
            self.provider_receipt_digest is not None
            and _DIGEST.fullmatch(self.provider_receipt_digest) is None
        ):
            raise ValueError("dispatch result requires a valid provider_receipt_digest when set")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("dispatch result requires timezone-aware recorded_at")
        expected = _result_digest(
            attempt_identity_digest=self.attempt_identity_digest,
            claim_digest=self.claim_digest,
            outcome=self.outcome,
            provider_receipt_digest=self.provider_receipt_digest,
            recorded_at=self.recorded_at,
        )
        if self.result_digest != expected:
            raise ValueError("dispatch result digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        attempt_identity_digest: str,
        claim_digest: str,
        outcome: str,
        provider_receipt_digest: str | None,
        recorded_at: datetime,
    ) -> RecoveryDispatchResult:
        digest = _result_digest(
            attempt_identity_digest=attempt_identity_digest,
            claim_digest=claim_digest,
            outcome=outcome,
            provider_receipt_digest=provider_receipt_digest,
            recorded_at=recorded_at,
        )
        return cls(
            attempt_identity_digest=attempt_identity_digest,
            claim_digest=claim_digest,
            outcome=outcome,
            provider_receipt_digest=provider_receipt_digest,
            recorded_at=recorded_at,
            result_digest=digest,
        )


# ---------------------------------------------------------------------------
# Approval and safeguard evidence binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveryApprovalEvidence:
    """Human approval evidence for one recovery attempt, separate from the original."""

    attempt_identity_digest: str
    approval_digest: str
    approved_at: datetime
    approver_identity: str
    evidence_digest: str
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False or self.approval_authority is not False:
            raise ValueError("recovery approval evidence MUST NOT grant authority")
        if _DIGEST.fullmatch(self.attempt_identity_digest) is None:
            raise ValueError("approval evidence requires a valid attempt_identity_digest")
        if _DIGEST.fullmatch(self.approval_digest) is None:
            raise ValueError("approval evidence requires a valid approval_digest")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("approval evidence requires timezone-aware approved_at")
        if not self.approver_identity or not self.approver_identity.strip():
            raise ValueError("approval evidence requires an approver_identity")
        if _DIGEST.fullmatch(self.evidence_digest) is None:
            raise ValueError("approval evidence requires a valid evidence_digest")
        expected = content_digest(
            {
                "attempt_identity_digest": self.attempt_identity_digest,
                "approval_digest": self.approval_digest,
                "approved_at": self.approved_at.astimezone(UTC).isoformat(),
                "approver_identity": self.approver_identity,
                "execution_authority": False,
                "approval_authority": False,
            }
        )
        if self.evidence_digest != expected:
            raise ValueError("approval evidence digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        attempt_identity_digest: str,
        approval_digest: str,
        approved_at: datetime,
        approver_identity: str,
    ) -> RecoveryApprovalEvidence:
        digest = content_digest(
            {
                "attempt_identity_digest": attempt_identity_digest,
                "approval_digest": approval_digest,
                "approved_at": approved_at.astimezone(UTC).isoformat(),
                "approver_identity": approver_identity,
                "execution_authority": False,
                "approval_authority": False,
            }
        )
        return cls(
            attempt_identity_digest=attempt_identity_digest,
            approval_digest=approval_digest,
            approved_at=approved_at,
            approver_identity=approver_identity,
            evidence_digest=digest,
        )


@dataclass(frozen=True, slots=True)
class RecoverySafeguardEvidence:
    """Action-bound safeguard evidence separate from admission."""

    attempt_identity_digest: str
    safeguard_bundle_digest: str
    completed_at: datetime
    evidence_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("safeguard evidence MUST NOT grant execution authority")
        if _DIGEST.fullmatch(self.attempt_identity_digest) is None:
            raise ValueError("safeguard evidence requires a valid attempt_identity_digest")
        if _DIGEST.fullmatch(self.safeguard_bundle_digest) is None:
            raise ValueError("safeguard evidence requires a valid safeguard_bundle_digest")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("safeguard evidence requires timezone-aware completed_at")
        if _DIGEST.fullmatch(self.evidence_digest) is None:
            raise ValueError("safeguard evidence requires a valid evidence_digest")
        expected = content_digest(
            {
                "attempt_identity_digest": self.attempt_identity_digest,
                "safeguard_bundle_digest": self.safeguard_bundle_digest,
                "completed_at": self.completed_at.astimezone(UTC).isoformat(),
                "execution_authority": False,
            }
        )
        if self.evidence_digest != expected:
            raise ValueError("safeguard evidence digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        attempt_identity_digest: str,
        safeguard_bundle_digest: str,
        completed_at: datetime,
    ) -> RecoverySafeguardEvidence:
        digest = content_digest(
            {
                "attempt_identity_digest": attempt_identity_digest,
                "safeguard_bundle_digest": safeguard_bundle_digest,
                "completed_at": completed_at.astimezone(UTC).isoformat(),
                "execution_authority": False,
            }
        )
        return cls(
            attempt_identity_digest=attempt_identity_digest,
            safeguard_bundle_digest=safeguard_bundle_digest,
            completed_at=completed_at,
            evidence_digest=digest,
        )


# ---------------------------------------------------------------------------
# Idempotency key derivation
# ---------------------------------------------------------------------------


def recovery_attempt_idempotency_key(identity: RecoveryAttemptIdentity) -> str:
    """Derive one stable idempotency key from the immutable attempt identity."""

    return str(
        content_digest(
            {
                "purpose": "recovery-attempt-dispatch",
                "identity_digest": identity.identity_digest,
                "attempt_number": identity.attempt_number,
            }
        )
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _attempt_identity_digest(
    *,
    process_id: str,
    failed_compensation_proposal_digest: str,
    hold_revision: int,
    recovery_action_type: str,
    recovery_payload_digest: str,
    target_digest: str,
    source_revision: str,
    attempt_number: int,
) -> str:
    return str(
        content_digest(
            {
                "process_id": process_id,
                "failed_compensation_proposal_digest": failed_compensation_proposal_digest,
                "hold_revision": hold_revision,
                "recovery_action_type": recovery_action_type,
                "recovery_payload_digest": recovery_payload_digest,
                "target_digest": target_digest,
                "source_revision": source_revision,
                "attempt_number": attempt_number,
            }
        )
    )


def _claim_digest(
    *,
    attempt_identity_digest: str,
    hold_revision: int,
    claim_revision: int,
    idempotency_key: str,
    claimed_at: datetime,
) -> str:
    return str(
        content_digest(
            {
                "attempt_identity_digest": attempt_identity_digest,
                "hold_revision": hold_revision,
                "claim_revision": claim_revision,
                "idempotency_key": idempotency_key,
                "claimed_at": claimed_at.astimezone(UTC).isoformat(),
            }
        )
    )


def _result_digest(
    *,
    attempt_identity_digest: str,
    claim_digest: str,
    outcome: str,
    provider_receipt_digest: str | None,
    recorded_at: datetime,
) -> str:
    return str(
        content_digest(
            {
                "attempt_identity_digest": attempt_identity_digest,
                "claim_digest": claim_digest,
                "outcome": outcome,
                "provider_receipt_digest": provider_receipt_digest,
                "recorded_at": recorded_at.astimezone(UTC).isoformat(),
            }
        )
    )


__all__ = [
    "RecoveryApprovalEvidence",
    "RecoveryAttemptIdentity",
    "RecoveryAttemptRejectionReason",
    "RecoveryDispatchOutcome",
    "RecoveryDispatchResult",
    "RecoveryPreDispatchClaim",
    "RecoverySafeguardEvidence",
    "recovery_attempt_idempotency_key",
]
