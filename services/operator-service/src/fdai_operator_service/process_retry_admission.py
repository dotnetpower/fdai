"""Read-only retry admission over one terminal Process attempt."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_EFFECT_FREE_FAILURE_REASONS = frozenset(
    {
        "approval_provider_not_configured",
        "approval_rejected",
        "approval_requester_unavailable",
        "approval_timed_out",
        "enforce_action_dispatcher_not_configured",
        "gate_blocked",
        "guard_blocked_enforce",
        "invalid_decision_outcome",
        "parallel_branch_failed",
        "unknown_action_type",
        "unsupported_step_kind",
        "workflow_sensitive_params_unsupported",
    }
)
_BLOCKING_EVENTS = frozenset(
    {
        "action.dispatched",
        "compensation.started",
        "compensation.dispatched",
        "process.cancellation-requested",
    }
)


def retry_is_permitted(
    *,
    status: str,
    events: Sequence[Mapping[str, object]],
    attempt: int,
    max_attempts: int = 3,
) -> bool:
    """Mirror runtime retry evidence without granting final transition authority."""
    if status not in {"failed", "timed_out"} or attempt >= max_attempts:
        return False
    attempt_events = [event for event in events if _event_attempt(event) == attempt]
    if any(event.get("kind") in _BLOCKING_EVENTS for event in attempt_events):
        return False
    failed = next(
        (
            event
            for event in reversed(attempt_events)
            if event.get("kind") in {"step.failed", "process.timed_out"}
            and isinstance(event.get("step_id"), str)
        ),
        None,
    )
    if failed is None:
        return False
    payload = failed.get("payload")
    if not isinstance(payload, Mapping):
        return False
    reason = payload.get("reason")
    has_approval = any(event.get("kind") == "approval.requested" for event in attempt_events)
    if has_approval and reason not in {"approval_rejected", "approval_timed_out"}:
        return False
    return isinstance(reason, str) and reason in _EFFECT_FREE_FAILURE_REASONS


def _event_attempt(event: Mapping[str, object]) -> int:
    attempt = event.get("attempt", 1)
    return attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else -1


__all__ = ["retry_is_permitted"]
