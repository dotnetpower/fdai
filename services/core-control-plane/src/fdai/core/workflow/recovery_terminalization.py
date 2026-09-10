"""Atomic terminalization of verified held recovery (#658).

Consume one current successful recovery completion claim with hold release,
then terminalize the Process and Saga audit through a replay-healable
completion outbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.recovery_effect_claim import (
    EffectCompletionClaim,
    is_current_success,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


# ---------------------------------------------------------------------------
# Terminal completion digest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveryCompletionDigest:
    """Stable binding of all identities consumed in the terminal transition."""

    process_id: str
    saga_id: str
    expected_process_revision: int
    resulting_process_revision: int
    recovery_attempt_digest: str
    effect_claim_generation: int
    effect_claim_digest: str
    release_receipt_digest: str
    terminal_event_digest: str
    audit_payload_digest: str
    completion_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("recovery completion digest MUST NOT grant execution authority")
        if not self.process_id or not self.process_id.strip():
            raise ValueError("completion digest requires a process_id")
        if not self.saga_id or not self.saga_id.strip():
            raise ValueError("completion digest requires a saga_id")
        if (
            not isinstance(self.expected_process_revision, int)
            or self.expected_process_revision < 0
        ):
            raise ValueError("expected_process_revision MUST be >= 0")
        if self.resulting_process_revision != self.expected_process_revision + 1:
            raise ValueError("resulting_process_revision MUST be exactly expected + 1")
        if not isinstance(self.effect_claim_generation, int) or self.effect_claim_generation < 1:
            raise ValueError("effect_claim_generation MUST be positive")
        for field_name in (
            "recovery_attempt_digest",
            "effect_claim_digest",
            "release_receipt_digest",
            "terminal_event_digest",
            "audit_payload_digest",
            "completion_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"completion digest requires a valid {field_name}")
        expected = _compute_completion_digest(self)
        if self.completion_digest != expected:
            raise ValueError("completion digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        process_id: str,
        saga_id: str,
        expected_process_revision: int,
        recovery_attempt_digest: str,
        effect_claim_generation: int,
        effect_claim_digest: str,
        release_receipt_digest: str,
        terminal_event_digest: str,
        audit_payload_digest: str,
    ) -> RecoveryCompletionDigest:
        digest = content_digest(
            {
                "process_id": process_id,
                "saga_id": saga_id,
                "expected_process_revision": expected_process_revision,
                "resulting_process_revision": expected_process_revision + 1,
                "recovery_attempt_digest": recovery_attempt_digest,
                "effect_claim_generation": effect_claim_generation,
                "effect_claim_digest": effect_claim_digest,
                "release_receipt_digest": release_receipt_digest,
                "terminal_event_digest": terminal_event_digest,
                "audit_payload_digest": audit_payload_digest,
                "execution_authority": False,
                "completion_digest": None,
            }
        )
        return cls(
            process_id=process_id,
            saga_id=saga_id,
            expected_process_revision=expected_process_revision,
            resulting_process_revision=expected_process_revision + 1,
            recovery_attempt_digest=recovery_attempt_digest,
            effect_claim_generation=effect_claim_generation,
            effect_claim_digest=effect_claim_digest,
            release_receipt_digest=release_receipt_digest,
            terminal_event_digest=terminal_event_digest,
            audit_payload_digest=audit_payload_digest,
            completion_digest=digest,
        )


# ---------------------------------------------------------------------------
# Immutable receipt lookup
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseReceiptLookup:
    """Immutable index from pre-release-known identity to release receipt."""

    recovery_attempt_digest: str
    effect_claim_digest: str
    hold_revision: int
    release_receipt_digest: str
    lookup_digest: str

    def __post_init__(self) -> None:
        for name in (
            "recovery_attempt_digest",
            "effect_claim_digest",
            "release_receipt_digest",
            "lookup_digest",
        ):
            if _DIGEST.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"release receipt lookup requires a valid {name}")
        if not isinstance(self.hold_revision, int) or self.hold_revision < 1:
            raise ValueError("release receipt lookup hold_revision MUST be positive")
        expected = content_digest(
            {
                "recovery_attempt_digest": self.recovery_attempt_digest,
                "effect_claim_digest": self.effect_claim_digest,
                "hold_revision": self.hold_revision,
                "release_receipt_digest": self.release_receipt_digest,
                "lookup_digest": None,
            }
        )
        if self.lookup_digest != expected:
            raise ValueError("release receipt lookup digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        recovery_attempt_digest: str,
        effect_claim_digest: str,
        hold_revision: int,
        release_receipt_digest: str,
    ) -> ReleaseReceiptLookup:
        digest = content_digest(
            {
                "recovery_attempt_digest": recovery_attempt_digest,
                "effect_claim_digest": effect_claim_digest,
                "hold_revision": hold_revision,
                "release_receipt_digest": release_receipt_digest,
                "lookup_digest": None,
            }
        )
        return cls(
            recovery_attempt_digest=recovery_attempt_digest,
            effect_claim_digest=effect_claim_digest,
            hold_revision=hold_revision,
            release_receipt_digest=release_receipt_digest,
            lookup_digest=digest,
        )


# ---------------------------------------------------------------------------
# Completion outbox
# ---------------------------------------------------------------------------


class OutboxDeliveryState:
    """Track delivery of Process event and Saga audit independently."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CompletionOutboxEntry:
    """One pending or delivered outbox item bound to its completion digest."""

    completion_digest: str
    delivery_kind: str  # "process_event" | "saga_audit"
    delivery_state: str
    payload_digest: str
    attempt_count: int
    last_attempt_at: datetime | None
    entry_digest: str

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.completion_digest) is None:
            raise ValueError("outbox entry requires a valid completion_digest")
        if self.delivery_kind not in {"process_event", "saga_audit"}:
            raise ValueError("outbox entry delivery_kind MUST be process_event or saga_audit")
        if self.delivery_state not in {
            OutboxDeliveryState.PENDING,
            OutboxDeliveryState.DELIVERED,
            OutboxDeliveryState.FAILED,
        }:
            raise ValueError("outbox entry delivery_state is invalid")
        if _DIGEST.fullmatch(self.payload_digest) is None:
            raise ValueError("outbox entry requires a valid payload_digest")
        if not isinstance(self.attempt_count, int) or self.attempt_count < 0:
            raise ValueError("outbox entry attempt_count MUST be non-negative")

    @classmethod
    def create_pending(
        cls,
        *,
        completion_digest: str,
        delivery_kind: str,
        payload_digest: str,
    ) -> CompletionOutboxEntry:
        entry_digest = content_digest(
            {
                "completion_digest": completion_digest,
                "delivery_kind": delivery_kind,
                "payload_digest": payload_digest,
            }
        )
        return cls(
            completion_digest=completion_digest,
            delivery_kind=delivery_kind,
            delivery_state=OutboxDeliveryState.PENDING,
            payload_digest=payload_digest,
            attempt_count=0,
            last_attempt_at=None,
            entry_digest=entry_digest,
        )


# ---------------------------------------------------------------------------
# Terminal transition guard
# ---------------------------------------------------------------------------


class TerminalTransitionRejection(StrEnum):
    """Why the terminal transition cannot proceed."""

    CLAIM_NOT_CURRENT_SUCCESS = "claim_not_current_success"
    CLAIM_EXPIRED = "claim_expired"
    CLAIM_REVOKED = "claim_revoked"
    HOLD_REVISION_MISMATCH = "hold_revision_mismatch"
    HOLD_REISSUED = "hold_reissued"
    PROCESS_REVISION_CONFLICT = "process_revision_conflict"
    RELEASE_RECEIPT_MISSING = "release_receipt_missing"
    FENCING_GENERATION_MISMATCH = "fencing_generation_mismatch"
    COMPLETION_DIGEST_MISMATCH = "completion_digest_mismatch"
    ALREADY_TERMINAL = "already_terminal"


def validate_terminal_preconditions(
    *,
    claim: EffectCompletionClaim,
    hold_revision: int,
    fencing_generation: int,
    process_revision: int,
    expected_completion_digest: str,
    release_receipt_digest: str | None,
    now: datetime,
) -> tuple[bool, tuple[TerminalTransitionRejection, ...]]:
    """Fail closed unless every precondition is met."""

    reasons: list[TerminalTransitionRejection] = []

    if not is_current_success(claim, now=now):
        reasons.append(TerminalTransitionRejection.CLAIM_NOT_CURRENT_SUCCESS)

    if now.tzinfo is not None and now.utcoffset() is not None:
        normalized = now.astimezone(UTC)
        if normalized >= claim.validity_end.astimezone(UTC):
            reasons.append(TerminalTransitionRejection.CLAIM_EXPIRED)

    if claim.superseded_by is not None:
        reasons.append(TerminalTransitionRejection.CLAIM_REVOKED)

    if claim.hold_revision != hold_revision:
        reasons.append(TerminalTransitionRejection.HOLD_REVISION_MISMATCH)

    if fencing_generation != hold_revision + 1:
        reasons.append(TerminalTransitionRejection.FENCING_GENERATION_MISMATCH)

    if release_receipt_digest is None:
        reasons.append(TerminalTransitionRejection.RELEASE_RECEIPT_MISSING)

    return (len(reasons) == 0, tuple(sorted(set(reasons), key=str)))


def check_replay_idempotent(
    *,
    committed_completion_digest: str | None,
    expected_completion_digest: str,
) -> bool:
    """True when the terminal commit already exists and matches."""

    return (
        committed_completion_digest is not None
        and committed_completion_digest == expected_completion_digest
    )


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _compute_completion_digest(cd: RecoveryCompletionDigest) -> str:
    return str(
        content_digest(
            {
                "process_id": cd.process_id,
                "saga_id": cd.saga_id,
                "expected_process_revision": cd.expected_process_revision,
                "resulting_process_revision": cd.resulting_process_revision,
                "recovery_attempt_digest": cd.recovery_attempt_digest,
                "effect_claim_generation": cd.effect_claim_generation,
                "effect_claim_digest": cd.effect_claim_digest,
                "release_receipt_digest": cd.release_receipt_digest,
                "terminal_event_digest": cd.terminal_event_digest,
                "audit_payload_digest": cd.audit_payload_digest,
                "execution_authority": False,
                "completion_digest": None,
            }
        )
    )


__all__ = [
    "CompletionOutboxEntry",
    "OutboxDeliveryState",
    "RecoveryCompletionDigest",
    "ReleaseReceiptLookup",
    "TerminalTransitionRejection",
    "check_replay_idempotent",
    "validate_terminal_preconditions",
]
