"""Provider-neutral execution result and lifecycle classifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fdai.shared.contracts.models import Mode


class DirectApiExecutionOutcome(StrEnum):
    """Lifecycle outcome for one direct-API execution attempt."""

    DISPATCHED = "dispatched"
    ALREADY_APPLIED = "already_applied"
    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    ABSTAINED_PRECONDITION = "abstained_precondition"
    STOPPED = "stopped"
    FAILED = "failed"
    DISPATCH_NOT_ATTEMPTED = "dispatch_not_attempted"
    AWAITING_EFFECT_EVIDENCE = "awaiting_effect_evidence"
    RECEIPT_TIMEOUT = "receipt_timeout"
    EXECUTION_UNKNOWN = "execution_unknown"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    POLICY_DENIED = "policy_denied"
    NETWORK_DENIED = "network_denied"
    REJECTED_MODE = "rejected_mode"
    REJECTED_INVARIANT = "rejected_invariant"
    REJECTED_CAPABILITY_UNAVAILABLE = "rejected_capability_unavailable"
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DirectApiExecutionResult:
    """Provider-neutral result returned by direct and isolated execution ports."""

    action_id: str
    outcome: DirectApiExecutionOutcome
    mode: Mode = Mode.SHADOW
    receipt_ref: str | None = None
    safeguard_bundle_digest: str | None = None
    rollback_succeeded: bool | None = None
    reason: str | None = None
    audit_context: dict[str, Any] = field(default_factory=dict)


class ExecutionLifecycleDisposition(StrEnum):
    """Operational meaning of one executor result at the current observation time."""

    ACCEPTED = "accepted"
    PENDING = "pending"
    NO_EFFECT = "no_effect"
    FAILED = "failed"


_ACCEPTED_OUTCOMES = frozenset(
    {
        "published",
        "already_existed",
        "dispatched",
        "already_applied",
    }
)
_PENDING_OUTCOMES = frozenset(
    {
        "publish_outcome_unknown",
        "awaiting_effect_evidence",
        "receipt_timeout",
        "execution_unknown",
    }
)
_NO_EFFECT_OUTCOMES = frozenset(
    {
        "dispatch_not_attempted",
        "abstained_blast_radius",
        "abstained_precondition",
        "abstained_render_error",
        "authentication_failed",
        "permission_denied",
        "policy_denied",
        "network_denied",
        "rejected_mode",
        "rejected_invariant",
        "rejected_capability_unavailable",
        "rejected_idempotency_conflict",
        "expired",
    }
)
_EFFECT_POSSIBLE_TERMINAL_OUTCOMES = frozenset({"stopped", "failed"})


def execution_lifecycle_disposition(outcome: object) -> ExecutionLifecycleDisposition:
    """Classify a serialized executor outcome without granting success authority."""

    value = getattr(outcome, "value", outcome)
    if not isinstance(value, str):
        return ExecutionLifecycleDisposition.FAILED
    if value in _ACCEPTED_OUTCOMES:
        return ExecutionLifecycleDisposition.ACCEPTED
    if value in _PENDING_OUTCOMES:
        return ExecutionLifecycleDisposition.PENDING
    if value in _NO_EFFECT_OUTCOMES:
        return ExecutionLifecycleDisposition.NO_EFFECT
    return ExecutionLifecycleDisposition.FAILED


def execution_outcome_is_pending(outcome: object) -> bool:
    """Return whether effect truth is still awaiting authoritative closure."""

    return execution_lifecycle_disposition(outcome) is ExecutionLifecycleDisposition.PENDING


def execution_outcome_is_no_effect(outcome: object) -> bool:
    """Return whether the current attempt provably reached no effect boundary."""

    return execution_lifecycle_disposition(outcome) is ExecutionLifecycleDisposition.NO_EFFECT


def execution_outcome_may_have_effect(outcome: object) -> bool:
    """Return whether independent effect reconciliation is required."""

    value = getattr(outcome, "value", outcome)
    return isinstance(value, str) and (
        value in _ACCEPTED_OUTCOMES
        or value in _PENDING_OUTCOMES
        or value in _EFFECT_POSSIBLE_TERMINAL_OUTCOMES
    )


__all__ = [
    "DirectApiExecutionOutcome",
    "DirectApiExecutionResult",
    "ExecutionLifecycleDisposition",
    "execution_lifecycle_disposition",
    "execution_outcome_is_no_effect",
    "execution_outcome_is_pending",
    "execution_outcome_may_have_effect",
]
