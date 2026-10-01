"""Cooperative cancellation helpers for agent critical sections."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


async def run_cancellation_safe_critical_section[T](operation: Awaitable[T]) -> T:
    """Finish one short critical section before propagating cancellation.

    Event-bus handler and maintenance deadlines are outer safety nets. Agent
    code must wrap only bounded, non-retrying commit windows here, such as
    ``reserve -> publish -> checkpoint``. If cancellation arrives while that
    window is active, the inner operation is shielded, awaited to completion,
    and then the original cancellation is re-raised. Long backend calls do not
    belong inside this helper.
    """

    task: asyncio.Future[T] = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


__all__ = ["run_cancellation_safe_critical_section"]
