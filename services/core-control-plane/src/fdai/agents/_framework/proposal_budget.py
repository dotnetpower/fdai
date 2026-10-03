"""Compatibility helpers for proposal rate-limit reservations."""

from __future__ import annotations

import inspect
from typing import Any, Protocol, cast


class ProposalBudgetReservation(Protocol):
    async def commit(self) -> None: ...

    async def release(self) -> None: ...


class _NoopReservation:
    async def commit(self) -> None:
        return None

    async def release(self) -> None:
        return None


async def reserve_proposal_budget(limiter: Any) -> ProposalBudgetReservation | None:
    """Reserve budget, adapting older ``allow``-only test doubles."""

    reserve = getattr(limiter, "reserve", None)
    if callable(reserve):
        result = reserve()
        reservation = await result if inspect.isawaitable(result) else result
        return cast(ProposalBudgetReservation | None, reservation)
    allow = getattr(limiter, "allow", None)
    if callable(allow) and allow():
        return _NoopReservation()
    return None


__all__ = ["ProposalBudgetReservation", "reserve_proposal_budget"]
