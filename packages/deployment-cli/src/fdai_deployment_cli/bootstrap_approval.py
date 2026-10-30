"""Scoped approval-source injection; terminal execution remains the default."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

ApprovalSource = Callable[[dict[str, object]], dict[str, object]]
_SOURCE: ContextVar[ApprovalSource | None] = ContextVar("bootstrap_approval_source", default=None)


@contextmanager
def approval_source(source: ApprovalSource) -> Iterator[None]:
    """Select a human decision adapter for this operation, without changing input()."""
    token = _SOURCE.set(source)
    try:
        yield
    finally:
        _SOURCE.reset(token)


def selected_source() -> ApprovalSource | None:
    return _SOURCE.get()


def require_decision(review: dict[str, object]) -> None:
    """Reject missing, denied, expired or differently bound adapter decisions."""
    source = selected_source()
    if source is None:
        raise ValueError("No injected approval source is selected")
    if datetime.fromisoformat(str(review["expires_at"])) <= datetime.now(UTC):
        raise ValueError("Exact checkpoint review has expired")
    decision = source(dict(review))
    if (
        not isinstance(decision, dict)
        or decision.get("approved") is not True
        or decision.get("digest") != review["digest"]
        or decision.get("confirmation") != review["confirmation_required"]
        or datetime.fromisoformat(str(review["expires_at"])) <= datetime.now(UTC)
    ):
        raise ValueError("Exact checkpoint approval was denied, expired or mismatched")


def approve_application_checkpoint(
    review: dict[str, Any],
    stage: str,
    destructive: int,
    *,
    actor_digest: Callable[[], str],
) -> tuple[str, str | None]:
    """Return the exact operation and pre-review actor; None keeps terminal approval."""
    historical_reconciliation = review.get("historical_reconciliation")
    residual_recovery = review.get("residual_recovery")
    residual_successor = review.get("residual_successor")
    operation = (
        str(residual_successor["operation"])
        if isinstance(residual_successor, dict)
        else str(residual_recovery["operation"])
        if isinstance(residual_recovery, dict)
        else str(historical_reconciliation["operation"])
        if isinstance(historical_reconciliation, dict)
        else stage
    )
    if selected_source() is None:
        return operation, None
    actor_before = actor_digest()
    expected = f"{operation}-apply"
    require_decision(
        {
            "digest": str(review["review_digest"]),
            "title": f"Approve exact {operation} plan",
            "details": [
                f"Plan digest: {review['plan_digest']}",
                f"Source commit: {review['source_commit']}",
                f"Delete or replacement actions: {destructive}",
                "Action counts: "
                + ", ".join(
                    f"{action}={count}"
                    for action, count in sorted(review["summary"]["action_counts"].items())
                ),
                *(
                    f"Resource type {name}: {count}"
                    for name, count in sorted(
                        review["summary"].get("resource_type_counts", {}).items()
                    )
                ),
                *(
                    f"{','.join(change['actions'])}: {change['address']}"
                    for change in review["summary"].get("resource_changes", [])
                ),
            ],
            "confirmation_required": f"{expected}-destructive" if destructive else expected,
            "expires_at": str(review["expires_at"]),
        }
    )
    return operation, actor_before
