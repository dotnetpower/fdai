"""Bounded process-local fan-out for the authenticated Live SSE surface."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

_CHANNEL: Final = "aw.pipeline.stages"
_KEEPALIVE: Final = b": keepalive\n\n"
_MAX_FIELD_CHARS: Final = 8_192
_MAX_DATA_CHARS: Final = 256 * 1_024


@dataclass(frozen=True, slots=True)
class LiveStreamEvent:
    """Represent one validated stage transition on the browser SSE wire."""

    event_id: str
    payload: Mapping[str, object]


class LiveStreamHub:
    """Fan validated stage events out through isolated bounded subscriber queues."""

    def __init__(self, *, maximum_queue_size: int = 1_024) -> None:
        if maximum_queue_size < 1:
            raise ValueError("maximum_queue_size MUST be positive")
        self._maximum_queue_size = maximum_queue_size
        self._subscribers: list[asyncio.Queue[LiveStreamEvent]] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: LiveStreamEvent) -> None:
        """Offer one event to every subscriber without blocking the producer."""
        async with self._lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            _offer_latest(queue, event)

    def subscribe(self) -> AsyncGenerator[LiveStreamEvent]:
        """Yield events observed after subscription and detach on cancellation."""
        return self._subscribe()

    async def _subscribe(self) -> AsyncGenerator[LiveStreamEvent]:
        queue: asyncio.Queue[LiveStreamEvent] = asyncio.Queue(maxsize=self._maximum_queue_size)
        async with self._lock:
            self._subscribers.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)


def make_live_stream_route(
    *,
    hub: LiveStreamHub,
    authorize: Callable[[Request], object],
    keepalive_seconds: float = 15.0,
) -> Route:
    """Build the authenticated read-only ``GET /live/stream`` route."""
    if keepalive_seconds <= 0:
        raise ValueError("keepalive_seconds MUST be positive")

    async def handler(request: Request) -> Response:
        authorize(request)

        return StreamingResponse(
            _live_chunks(
                hub=hub,
                is_disconnected=request.is_disconnected,
                keepalive_seconds=keepalive_seconds,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return Route("/live/stream", handler, methods=["GET"], name="live_stream")


async def _live_chunks(
    *,
    hub: LiveStreamHub,
    is_disconnected: Callable[[], Awaitable[bool]],
    keepalive_seconds: float,
) -> AsyncGenerator[bytes]:
    yield _encode_frame(
        "hello",
        {"event": "hello", "ts": _iso_timestamp(), "channel": _CHANNEL},
    )
    output: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1_024)
    stop = asyncio.Event()

    async def event_pump() -> None:
        async for event in hub.subscribe():
            if stop.is_set():
                break
            _offer_latest(output, _encode_event(event))

    async def keepalive_pump() -> None:
        while not stop.is_set():
            await asyncio.sleep(keepalive_seconds)
            if not stop.is_set():
                _offer_latest(output, _KEEPALIVE)

    event_task = asyncio.create_task(event_pump(), name="operator-live-events")
    keepalive_task = asyncio.create_task(keepalive_pump(), name="operator-live-keepalive")
    try:
        while not await is_disconnected():
            try:
                yield await asyncio.wait_for(output.get(), timeout=1.0)
            except TimeoutError:
                continue
    finally:
        stop.set()
        event_task.cancel()
        keepalive_task.cancel()
        await asyncio.gather(event_task, keepalive_task, return_exceptions=True)


def _offer_latest(queue: asyncio.Queue[Any], event: Any) -> None:
    try:
        queue.put_nowait(event)
        return
    except asyncio.QueueFull:
        pass
    try:
        queue.get_nowait()
    except asyncio.QueueEmpty:
        return
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:  # pragma: no cover - same-loop queue invariant
        return


def _encode_event(event: LiveStreamEvent) -> bytes:
    return (
        f"id: {_field(event.event_id)}\nevent: stage\ndata: {_json(event.payload)}\n\n"
    ).encode()


def _encode_frame(kind: str, payload: Mapping[str, object]) -> bytes:
    return f"event: {_field(kind)}\ndata: {_json(payload)}\n\n".encode()


def _field(value: str) -> str:
    flattened = value.replace("\r", " ").replace("\n", " ").strip()
    return flattened[:_MAX_FIELD_CHARS] or "message"


def _json(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(encoded) > _MAX_DATA_CHARS:
        raise ValueError("Live SSE payload exceeds the data size limit")
    return encoded.replace("\r", "\\r").replace("\n", "\\n")


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = ["LiveStreamEvent", "LiveStreamHub", "make_live_stream_route"]
