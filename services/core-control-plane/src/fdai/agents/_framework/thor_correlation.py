"""Atomic durable correlation resolution for Thor dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, cast


class _ActionRunLike(Protocol):
    correlation_id: str


CorrelationStatus = Literal[
    "acquired",
    "pending",
    "active",
    "execution_completed",
    "correlation_completed",
    "contended",
]


async def resolve_correlation_claim[RunT: _ActionRunLike](
    state_store: object,
    run: RunT,
) -> tuple[CorrelationStatus, RunT | None]:
    """Claim or resolve one correlation without running restart recovery."""

    claim = getattr(state_store, "claim_correlation_identity", None)
    if not callable(claim):
        return "acquired", None
    claim_exact = cast(
        Callable[
            [RunT],
            Awaitable[Literal["acquired", "existing", "completed", "contended"]],
        ],
        claim,
    )
    claim_status = await claim_exact(run)
    if claim_status == "completed":
        return "execution_completed", None
    if claim_status != "existing":
        return claim_status, None
    load = getattr(state_store, "load_correlation_identity", None)
    if not callable(load):
        raise RuntimeError("Thor atomic correlation store is incomplete")
    load_exact = cast(
        Callable[
            [RunT],
            Awaitable[tuple[Literal["pending", "active", "completed"], RunT | None]],
        ],
        load,
    )
    stored_status, existing = await load_exact(run)
    return (
        "correlation_completed" if stored_status == "completed" else stored_status,
        existing,
    )


__all__ = ["CorrelationStatus", "resolve_correlation_claim"]
