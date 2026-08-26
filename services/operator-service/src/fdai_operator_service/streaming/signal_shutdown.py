"""Publish process shutdown signals to active Operator SSE streams."""

from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType

from fdai_operator_service.contracts import (
    AsgiApplication,
    AsgiReceive,
    AsgiScope,
    AsgiSend,
)
from fdai_operator_service.streaming.shutdown import STREAM_SHUTDOWN_STATE

type SignalHandler = Callable[[int, FrameType | None], object] | int | None


class StreamShutdownSignalMiddleware:
    """Notify streams before the ASGI server waits for connections to close."""

    def __init__(self, app: AsgiApplication) -> None:
        self._app = app

    async def __call__(
        self,
        scope: AsgiScope,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        if scope.get("type") != "lifespan":
            await self._app(scope, receive, send)
            return
        with _chain_shutdown_signals(self._app):
            await self._app(scope, receive, send)


@contextmanager
def _chain_shutdown_signals(app: object) -> Iterator[None]:
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handlers: dict[int, SignalHandler] = {}

    def handle_shutdown(signum: int, frame: FrameType | None) -> None:
        _publish_stream_shutdown(app)
        previous = previous_handlers[signum]
        if callable(previous):
            previous(signum, frame)
        elif previous == signal.SIG_DFL:
            signal.signal(signum, signal.SIG_DFL)
            signal.raise_signal(signum)

    for signum in _handled_signals():
        previous_handlers[signum] = signal.signal(signum, handle_shutdown)
    try:
        yield
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def _handled_signals() -> tuple[int, ...]:
    handled: list[int] = [signal.SIGINT, signal.SIGTERM]
    sigbreak = getattr(signal, "SIGBREAK", None)
    if isinstance(sigbreak, int):
        handled.append(sigbreak)
    return tuple(handled)


def _publish_stream_shutdown(app: object) -> None:
    candidate: object | None = app
    visited: set[int] = set()
    while candidate is not None and id(candidate) not in visited:
        visited.add(id(candidate))
        state = getattr(candidate, "state", None)
        event = getattr(state, STREAM_SHUTDOWN_STATE, None)
        if isinstance(event, asyncio.Event):
            event.set()
            return
        candidate = getattr(candidate, "app", None)


__all__ = ["StreamShutdownSignalMiddleware"]
