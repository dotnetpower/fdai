"""Busy-input lifecycle helpers shared by one-shot and streaming chat routes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fdai.core.conversation import ActiveConversationTurn, BusyInputCoordinator

MAX_STEER_RERUNS = 4


class ChatTurnInterruptedError(RuntimeError):
    """The authenticated operator cancelled only the active narrator call."""


async def await_with_interrupt[T](
    awaitable: Awaitable[T],
    *,
    active_turn: ActiveConversationTurn | None,
) -> T:
    if active_turn is None:
        return await awaitable
    backend_task = asyncio.ensure_future(awaitable)
    cancel_task = asyncio.create_task(active_turn.cancel_event.wait())
    try:
        done, _ = await asyncio.wait(
            {backend_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if backend_task in done:
            return await backend_task
        backend_task.cancel()
        await asyncio.gather(backend_task, return_exceptions=True)
        raise ChatTurnInterruptedError("chat turn interrupted")
    finally:
        cancel_task.cancel()
        await asyncio.gather(cancel_task, return_exceptions=True)


async def answer_with_busy_input(
    *,
    invoke: Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]],
    history: list[dict[str, str]],
    coordinator: BusyInputCoordinator | None,
    active_turn: ActiveConversationTurn | None,
) -> dict[str, Any]:
    steers_used = 0
    while steers_used < MAX_STEER_RERUNS and await append_next_steer(
        history=history,
        coordinator=coordinator,
        active_turn=active_turn,
    ):
        steers_used += 1
    reply = await await_with_interrupt(invoke(history), active_turn=active_turn)
    while steers_used < MAX_STEER_RERUNS and await append_next_steer(
        history=history,
        coordinator=coordinator,
        active_turn=active_turn,
    ):
        steers_used += 1
        reply = await await_with_interrupt(invoke(history), active_turn=active_turn)
    return reply


async def append_next_steer(
    *,
    history: list[dict[str, str]],
    coordinator: BusyInputCoordinator | None,
    active_turn: ActiveConversationTurn | None,
) -> bool:
    if coordinator is None or active_turn is None:
        return False
    guidance = await coordinator.safe_boundary(
        session_id=active_turn.session_id,
        principal_id=active_turn.principal_id,
    )
    if guidance is None:
        return False
    history.append({"role": "user", "content": guidance.input.content})
    return True


async def interruptible_events[T](
    source: AsyncIterator[T],
    *,
    active_turn: ActiveConversationTurn | None,
) -> AsyncIterator[T]:
    iterator = source.__aiter__()
    while True:
        try:
            event = await await_with_interrupt(anext(iterator), active_turn=active_turn)
        except StopAsyncIteration:
            return
        yield event


__all__ = [
    "ChatTurnInterruptedError",
    "MAX_STEER_RERUNS",
    "answer_with_busy_input",
    "append_next_steer",
    "await_with_interrupt",
    "interruptible_events",
]
