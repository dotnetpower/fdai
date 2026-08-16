"""Publish application shutdown to long-lived server-sent event streams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Final

from starlette.requests import Request

STREAM_SHUTDOWN_STATE: Final = "stream_shutdown"


def shutting_down(request: Request) -> bool:
    """Report whether the application already began its shutdown sequence.

    An SSE loop that only observes client disconnection keeps the connection
    open until the client leaves, which blocks a graceful server shutdown
    indefinitely.
    """
    event = _event(request)
    return event is not None and event.is_set()


def shutdown_event(request: Request) -> asyncio.Event | None:
    """Return the published shutdown event so a stream can await it directly."""
    return _event(request)


async def next_or_shutdown[Event](
    source: AsyncIterator[Event],
    stop: asyncio.Event | None,
) -> Event | None:
    """Return the next event, or ``None`` once the stream ends or shutdown begins.

    Checking a shutdown flag only after an event arrives leaves an idle stream
    blocked in its upstream await, which is the exact indefinite hold graceful
    shutdown has to avoid. Racing the two makes the stop observable while idle.
    """
    if stop is None:
        try:
            return await anext(source)
        except StopAsyncIteration:
            return None
    next_task: asyncio.Task[Event] = asyncio.ensure_future(anext(source))
    stop_task = asyncio.ensure_future(stop.wait())
    try:
        done, _pending = await asyncio.wait(
            {next_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    except BaseException:
        next_task.cancel()
        stop_task.cancel()
        await asyncio.gather(next_task, stop_task, return_exceptions=True)
        raise
    if stop_task in done:
        if not next_task.done():
            next_task.cancel()
        await asyncio.gather(next_task, stop_task, return_exceptions=True)
        return None
    stop_task.cancel()
    await asyncio.gather(stop_task, return_exceptions=True)
    try:
        return next_task.result()
    except StopAsyncIteration:
        return None


def _event(request: Request) -> asyncio.Event | None:
    application = request.scope.get("app")
    if application is None:
        return None
    state = getattr(application, "state", None)
    if state is None:
        return None
    event = getattr(state, STREAM_SHUTDOWN_STATE, None)
    return event if isinstance(event, asyncio.Event) else None


__all__ = [
    "STREAM_SHUTDOWN_STATE",
    "next_or_shutdown",
    "shutdown_event",
    "shutting_down",
]
