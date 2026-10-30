"""Scoped approval-source injection; terminal execution remains the default."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

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
