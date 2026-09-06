"""Bounded process-local fan-out for the authenticated Live SSE surface."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Final

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from fdai_operator_service.streaming.shutdown import shutting_down

_CHANNEL: Final = "fdai.pipeline.stages"
_KEEPALIVE: Final = b": keepalive\n\n"
_MAX_FIELD_CHARS: Final = 8_192
_MAX_DATA_CHARS: Final = 256 * 1_024


@dataclass(frozen=True, slots=True)
class LiveStreamEvent:
    """Represent one validated stage transition on the browser SSE wire."""

    event_id: str
    payload: Mapping[str, object]
    event_type: str = "stage"


class LiveStreamHub:
    """Fan validated events out with isolated queues and optional bounded replay."""

    def __init__(
        self,
        *,
        maximum_queue_size: int = 1_024,
        latest_key: Callable[[LiveStreamEvent], str | None] | None = None,
        replay_capacity: int = 0,
        replay_window_seconds: float = 0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if maximum_queue_size < 1:
            raise ValueError("maximum_queue_size MUST be positive")
        self._maximum_queue_size = maximum_queue_size
        self._latest_key = latest_key
        self._latest_events: dict[str, LiveStreamEvent] = {}
        self._source_event: LiveStreamEvent | None = None
        self._replay_window_seconds = 0.0
        self._recent_events: deque[tuple[float, LiveStreamEvent]] = deque()
        self._clock = clock
        self._subscribers: list[asyncio.Queue[LiveStreamEvent]] = []
        self._lock = asyncio.Lock()
        if replay_capacity > 0 or replay_window_seconds > 0:
            self.enable_recent_replay(
                capacity=replay_capacity,
                window_seconds=replay_window_seconds,
            )

    def enable_recent_replay(self, *, capacity: int, window_seconds: float) -> None:
        """Enable bounded replay before this hub accepts subscribers."""
        if capacity <= 0 or window_seconds <= 0:
            raise ValueError("replay capacity and window MUST be positive")
        if self._latest_key is not None:
            raise ValueError("latest-key and recent-window replay modes are mutually exclusive")
        if self._subscribers:
            raise RuntimeError("recent replay MUST be configured before subscription")
        self._replay_window_seconds = window_seconds
        self._recent_events = deque(maxlen=capacity)

    async def publish(self, event: LiveStreamEvent) -> None:
        """Offer one event to every subscriber without blocking the producer."""
        async with self._lock:
            if self._latest_key is not None:
                key = self._latest_key(event)
                if key:
                    self._latest_events[key] = event
            if self._replay_window_seconds > 0:
                published_at = self._clock()
                self._recent_events.append((published_at, event))
                self._prune_recent_events(published_at)
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            _offer_latest(queue, event)

    async def publish_source(self, event: LiveStreamEvent) -> None:
        """Publish and retain one validated source-readiness observation."""
        if event.event_type != "source":
            raise ValueError("source readiness event MUST use event_type=source")
        async with self._lock:
            self._source_event = event
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
            if self._source_event is not None:
                _offer_latest(queue, self._source_event)
            for event in self._latest_events.values():
                _offer_latest(queue, event)
            if self._replay_window_seconds > 0:
                self._prune_recent_events(self._clock())
                for _, event in self._recent_events:
                    _offer_latest(queue, event)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                if queue in self._subscribers:
                    self._subscribers.remove(queue)

    def _prune_recent_events(self, now: float) -> None:
        cutoff = now - self._replay_window_seconds
        while self._recent_events and self._recent_events[0][0] < cutoff:
            self._recent_events.popleft()


def make_live_stream_route(
    *,
    hub: LiveStreamHub,
    authorize: Callable[[Request], object],
    keepalive_seconds: float = 15.0,
    path: str = "/live/stream",
    channel: str = _CHANNEL,
    route_name: str = "live_stream",
) -> Route:
    """Build one authenticated read-only SSE route over a bounded hub."""
    if keepalive_seconds <= 0:
        raise ValueError("keepalive_seconds MUST be positive")
    if not path.startswith("/") or not channel or not route_name:
        raise ValueError("SSE path, channel, and route_name MUST be non-empty")

    async def handler(request: Request) -> Response:
        authorize(request)

        return StreamingResponse(
            _live_chunks(
                hub=hub,
                is_disconnected=request.is_disconnected,
                is_shutting_down=lambda: shutting_down(request),
                keepalive_seconds=keepalive_seconds,
                channel=channel,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return Route(path, handler, methods=["GET"], name=route_name)


async def _live_chunks(
    *,
    hub: LiveStreamHub,
    is_disconnected: Callable[[], Awaitable[bool]],
    keepalive_seconds: float,
    is_shutting_down: Callable[[], bool] = lambda: False,
    channel: str = _CHANNEL,
) -> AsyncGenerator[bytes]:
    yield _encode_frame(
        "hello",
        {"event": "hello", "ts": _iso_timestamp(), "channel": channel},
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
        while not is_shutting_down() and not await is_disconnected():
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
        f"id: {_field(event.event_id)}\nevent: {_field(event.event_type)}\n"
        f"data: {_json(event.payload)}\n\n"
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
