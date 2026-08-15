"""Publish application shutdown to long-lived server-sent event streams."""

from __future__ import annotations

import asyncio
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


def _event(request: Request) -> asyncio.Event | None:
    application = request.scope.get("app")
    if application is None:
        return None
    state = getattr(application, "state", None)
    if state is None:
        return None
    event = getattr(state, STREAM_SHUTDOWN_STATE, None)
    return event if isinstance(event, asyncio.Event) else None


__all__ = ["STREAM_SHUTDOWN_STATE", "shutting_down"]
