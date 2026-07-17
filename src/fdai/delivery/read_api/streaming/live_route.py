"""Starlette route and subscriber loop for the live SSE surface."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from fdai.delivery.read_api.streaming.sse_protocol import (
    encode_sse_event,
    encode_sse_frame,
    iso_ts_utc,
)
from fdai.shared.providers.sse import SseSink

_LOGGER = logging.getLogger(__name__)
_KEEPALIVE_COMMENT = b": keepalive\n\n"


def make_live_stream_route(
    *,
    sink: SseSink,
    channel: str,
    path: str,
    keepalive_seconds: float,
    authorize: Callable[[Request], Awaitable[str]],
) -> Route:
    """Return the authenticated, read-only SSE route."""

    async def handler(request: Request) -> Response:
        oid = await authorize(request)
        _LOGGER.info("live_stream_open", extra={"actor": oid, "channel": channel})

        async def stream() -> AsyncIterator[bytes]:
            yield encode_sse_frame(
                {"event": "hello", "ts": iso_ts_utc(), "channel": channel},
                kind="hello",
            )
            out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1024)
            stop = asyncio.Event()

            async def event_pump() -> None:
                try:
                    async for event in sink.subscribe(channel):
                        if stop.is_set():
                            break
                        try:
                            out_queue.put_nowait(encode_sse_event(event))
                        except asyncio.QueueFull:
                            pass
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.warning(
                        "live_stream_event_pump_failed",
                        extra={"channel": channel},
                        exc_info=True,
                    )
                    stop.set()

            async def keepalive_pump() -> None:
                try:
                    while not stop.is_set():
                        await asyncio.sleep(keepalive_seconds)
                        if stop.is_set():
                            break
                        try:
                            out_queue.put_nowait(_KEEPALIVE_COMMENT)
                        except asyncio.QueueFull:
                            pass
                except asyncio.CancelledError:
                    raise

            event_task = asyncio.create_task(event_pump(), name="fdai.live.event-pump")
            keepalive_task = asyncio.create_task(keepalive_pump(), name="fdai.live.keepalive")
            try:
                while True:
                    try:
                        chunk = await asyncio.wait_for(out_queue.get(), timeout=1.0)
                    except TimeoutError:
                        chunk = None
                    if chunk is not None:
                        yield chunk
                    if stop.is_set() and out_queue.empty():
                        break
                    if await request.is_disconnected():
                        break
            finally:
                stop.set()
                event_task.cancel()
                keepalive_task.cancel()
                await asyncio.gather(event_task, keepalive_task, return_exceptions=True)
                _LOGGER.info("live_stream_close", extra={"actor": oid, "channel": channel})

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return Route(path, handler, methods=["GET"])


__all__ = ["make_live_stream_route"]
