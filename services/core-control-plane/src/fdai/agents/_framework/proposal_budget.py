"""Compatibility helpers for proposal rate-limit reservations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus


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


async def publish_reserved_proposal(
    *,
    bus: Callable[[], PantheonBus | None],
    principal: str,
    topic: str,
    payload: dict[str, Any],
    reservation: ProposalBudgetReservation,
    allowed: Callable[[str, dict[str, Any]], bool],
    record_behavior: Callable[[str], None],
) -> bool:
    """Recheck publication eligibility after reservation; release unused budget."""
    transport = bus()
    if transport is None:
        await reservation.release()
        record_behavior("rate_limit_flush_transport_unavailable")
        return False
    if not allowed(topic, payload):
        await reservation.release()
        return False
    await transport.publish(principal, topic, payload)
    await reservation.commit()
    return True


__all__ = [
    "ProposalBudgetReservation",
    "publish_reserved_proposal",
    "reserve_proposal_budget",
]
