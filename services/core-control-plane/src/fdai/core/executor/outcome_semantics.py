"""Shared execution-outcome classifications for orchestration consumers."""

from __future__ import annotations

from enum import StrEnum


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
    "ExecutionLifecycleDisposition",
    "execution_lifecycle_disposition",
    "execution_outcome_is_no_effect",
    "execution_outcome_is_pending",
    "execution_outcome_may_have_effect",
]
