"""Bounded process-local fan-out for the authenticated Live SSE surface."""

from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict, deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Final
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from fdai_operator_service.streaming.shutdown import shutting_down

_CHANNEL: Final = "fdai.pipeline.stages"
_KEEPALIVE: Final = b": keepalive\n\n"
_MAX_FIELD_CHARS: Final = 8_192
_MAX_DATA_BYTES: Final = 256 * 1_024
_CURSOR: Final = re.compile(r"^(?P<epoch>[a-f0-9]{16}):(?P<sequence>[1-9][0-9]{0,18})$")


@dataclass(frozen=True, slots=True)
class LiveStreamEvent:
    """Represent one validated transition on the browser SSE wire."""

    event_id: str
    payload: Mapping[str, object]
    event_type: str = "stage"


@dataclass(frozen=True, slots=True)
class LiveStreamDelivery:
    """Carry one connection delivery with optional resumable delta metadata."""

    event: LiveStreamEvent
    sequence: int | None
    snapshot: bool = False
    dropped_before: int = 0


@dataclass(slots=True)
class _LiveSubscriber:
    queue: asyncio.Queue[LiveStreamDelivery]
    dropped_deltas: int = 0


class LiveStreamHub:
    """Fan validated events out with isolated queues and bounded replay."""

    def __init__(
        self,
        *,
        maximum_queue_size: int = 1_024,
        latest_key: Callable[[LiveStreamEvent], str | None] | None = None,
        latest_capacity: int = 256,
        replay_capacity: int = 0,
        replay_window_seconds: float = 0,
        clock: Callable[[], float] = monotonic,
        stream_epoch: str | None = None,
    ) -> None:
        if maximum_queue_size < 1:
            raise ValueError("maximum_queue_size MUST be positive")
        if latest_capacity < 1:
            raise ValueError("latest_capacity MUST be positive")
        self._maximum_queue_size = maximum_queue_size
        self._latest_key = latest_key
        self._latest_capacity = latest_capacity
        self._latest_events: OrderedDict[str, LiveStreamEvent] = OrderedDict()
        self._source_event: LiveStreamEvent | None = None
        self._replay_window_seconds = 0.0
        self._recent_events: deque[tuple[float, LiveStreamDelivery]] = deque()
        self._clock = clock
        self._stream_epoch = stream_epoch or uuid4().hex[:16]
        if re.fullmatch(r"[a-f0-9]{16}", self._stream_epoch) is None:
            raise ValueError("stream_epoch MUST contain 16 lowercase hexadecimal characters")
        self._next_sequence = 1
        self._subscribers: list[_LiveSubscriber] = []
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
        if self._subscribers:
            raise RuntimeError("recent replay MUST be configured before subscription")
        self._replay_window_seconds = window_seconds
        self._recent_events = deque(maxlen=capacity)

    @property
    def stream_epoch(self) -> str:
        return self._stream_epoch

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    async def publish(self, event: LiveStreamEvent) -> None:
        """Offer one cursor-bearing delta without blocking its producer."""
        _json(event.payload)
        async with self._lock:
            delivery = LiveStreamDelivery(event=event, sequence=self._next_sequence)
            self._next_sequence += 1
            if self._latest_key is not None:
                key = self._latest_key(event)
                if key:
                    self._remember_latest(key, event)
            if self._replay_window_seconds > 0:
                published_at = self._clock()
                self._recent_events.append((published_at, delivery))
                self._prune_recent_events(published_at)
            for subscriber in self._subscribers:
                _offer_delivery(subscriber, delivery)

    async def seed_latest(self, events: tuple[LiveStreamEvent, ...]) -> None:
        """Seed unsequenced snapshots without manufacturing replayable deltas."""
        if self._latest_key is None and events:
            raise ValueError("latest snapshot seeding requires a latest-key function")
        keyed_events: list[tuple[str, LiveStreamEvent]] = []
        for event in events:
            key = self._latest_key(event) if self._latest_key is not None else None
            if key is None:
                raise ValueError("seeded event MUST have a latest snapshot key")
            keyed_events.append((key, event))
        async with self._lock:
            for key, event in keyed_events:
                self._remember_latest(key, event)

    def _remember_latest(self, key: str, event: LiveStreamEvent) -> None:
        self._latest_events[key] = event
        self._latest_events.move_to_end(key)
        while len(self._latest_events) > self._latest_capacity:
            self._latest_events.popitem(last=False)

    async def publish_source(self, event: LiveStreamEvent) -> None:
        """Publish and retain one validated source-readiness observation."""
        if event.event_type != "source":
            raise ValueError("source readiness event MUST use event_type=source")
        _json(event.payload)
        async with self._lock:
            self._source_event = event
            delivery = LiveStreamDelivery(event=event, sequence=None, snapshot=True)
            for subscriber in self._subscribers:
                _offer_delivery(subscriber, delivery)

    def subscribe(self) -> AsyncGenerator[LiveStreamEvent]:
        """Yield compatibility events and detach on cancellation."""
        return self._subscribe()

    async def _subscribe(self) -> AsyncGenerator[LiveStreamEvent]:
        async for delivery in self.subscribe_deliveries():
            yield delivery.event

    def subscribe_deliveries(
        self,
        *,
        after_sequence: int | None = None,
    ) -> AsyncGenerator[LiveStreamDelivery]:
        """Yield unsequenced snapshots followed by cursor-bearing deltas."""
        return self._subscribe_deliveries(after_sequence=after_sequence)

    async def _subscribe_deliveries(
        self,
        *,
        after_sequence: int | None,
    ) -> AsyncGenerator[LiveStreamDelivery]:
        subscriber = _LiveSubscriber(queue=asyncio.Queue(maxsize=self._maximum_queue_size))
        async with self._lock:
            self._subscribers.append(subscriber)
            if self._source_event is not None:
                _offer_delivery(
                    subscriber,
                    LiveStreamDelivery(
                        event=self._source_event,
                        sequence=None,
                        snapshot=True,
                    ),
                )
            for event in self._latest_events.values():
                _offer_delivery(
                    subscriber,
                    LiveStreamDelivery(
                        event=event,
                        sequence=None,
                        snapshot=True,
                    ),
                )
            replay: list[LiveStreamDelivery] = []
            if self._replay_window_seconds > 0:
                self._prune_recent_events(self._clock())
                for _, delivery in self._recent_events:
                    if after_sequence is not None:
                        if delivery.sequence is not None and delivery.sequence > after_sequence:
                            replay.append(delivery)
                    elif self._latest_key is None or self._latest_key(delivery.event) is None:
                        replay.append(delivery)
                if after_sequence is not None and replay:
                    first_sequence = replay[0].sequence
                    if first_sequence is not None and first_sequence > after_sequence + 1:
                        replay[0] = replace(
                            replay[0],
                            dropped_before=first_sequence - after_sequence - 1,
                        )
                for delivery in replay:
                    _offer_delivery(subscriber, delivery)
            if (
                after_sequence is not None
                and not replay
                and self._next_sequence > after_sequence + 1
            ):
                subscriber.dropped_deltas = self._next_sequence - after_sequence - 1
        try:
            while True:
                yield await subscriber.queue.get()
        finally:
            async with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

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
    resumable: bool = True,
) -> Route:
    """Build one authenticated read-only SSE route over a bounded hub."""
    if keepalive_seconds <= 0:
        raise ValueError("keepalive_seconds MUST be positive")
    if not path.startswith("/") or not channel or not route_name:
        raise ValueError("SSE path, channel, and route_name MUST be non-empty")

    async def handler(request: Request) -> Response:
        authorize(request)
        cursor_epoch: str | None = None
        after_sequence: int | None = None
        if resumable:
            try:
                cursor_epoch, after_sequence = _last_event_cursor(request)
            except ValueError as exc:
                return Response(
                    str(exc),
                    status_code=400,
                    media_type="text/plain",
                )
            if (
                cursor_epoch == hub.stream_epoch
                and after_sequence is not None
                and after_sequence >= hub.next_sequence
            ):
                return Response(
                    "Last-Event-ID is ahead of the current stream",
                    status_code=400,
                    media_type="text/plain",
                )

        return StreamingResponse(
            _live_chunks(
                hub=hub,
                is_disconnected=request.is_disconnected,
                is_shutting_down=lambda: shutting_down(request),
                keepalive_seconds=keepalive_seconds,
                channel=channel,
                cursor_epoch=cursor_epoch,
                after_sequence=after_sequence,
                resumable=resumable,
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
    cursor_epoch: str | None = None,
    after_sequence: int | None = None,
    resumable: bool = True,
) -> AsyncGenerator[bytes]:
    yield _encode_frame(
        "hello",
        {
            "event": "hello",
            "ts": _iso_timestamp(),
            "channel": channel,
            "stream_epoch": hub.stream_epoch,
            "next_sequence": hub.next_sequence,
            "cursor_reset": (cursor_epoch is not None and cursor_epoch != hub.stream_epoch),
        },
    )
    same_epoch = cursor_epoch is None or cursor_epoch == hub.stream_epoch
    if cursor_epoch is not None and not same_epoch:
        yield _encode_frame(
            "gap",
            {
                "reason": "stream_epoch_changed",
                "stream_epoch": hub.stream_epoch,
                "ts": _iso_timestamp(),
            },
        )
    subscription = hub.subscribe_deliveries(after_sequence=after_sequence if same_epoch else None)
    next_delivery = asyncio.create_task(
        anext(subscription),
        name="operator-live-next-delivery",
    )
    try:
        while not is_shutting_down() and not await is_disconnected():
            completed, _ = await asyncio.wait(
                {next_delivery},
                timeout=keepalive_seconds,
            )
            if not completed:
                yield _KEEPALIVE
                continue
            delivery = next_delivery.result()
            yield (
                _encode_delivery(hub.stream_epoch, delivery)
                if resumable
                else _encode_legacy_delivery(delivery)
            )
            next_delivery = asyncio.create_task(
                anext(subscription),
                name="operator-live-next-delivery",
            )
    except StopAsyncIteration:
        return
    finally:
        next_delivery.cancel()
        await asyncio.gather(next_delivery, return_exceptions=True)
        await subscription.aclose()


def _offer_delivery(
    subscriber: _LiveSubscriber,
    delivery: LiveStreamDelivery,
) -> None:
    pending_drop_count = subscriber.dropped_deltas
    candidate = (
        replace(
            delivery,
            dropped_before=delivery.dropped_before + pending_drop_count,
        )
        if delivery.sequence is not None and pending_drop_count > 0
        else delivery
    )
    try:
        subscriber.queue.put_nowait(candidate)
        if delivery.sequence is not None:
            subscriber.dropped_deltas = 0
        return
    except asyncio.QueueFull:
        pass
    try:
        discarded = subscriber.queue.get_nowait()
    except asyncio.QueueEmpty:
        return
    if discarded.sequence is not None:
        subscriber.dropped_deltas += discarded.dropped_before + 1
    candidate = (
        replace(
            delivery,
            dropped_before=delivery.dropped_before + subscriber.dropped_deltas,
        )
        if delivery.sequence is not None and subscriber.dropped_deltas > 0
        else delivery
    )
    try:
        subscriber.queue.put_nowait(candidate)
        if delivery.sequence is not None:
            subscriber.dropped_deltas = 0
    except asyncio.QueueFull:  # pragma: no cover - same-loop queue invariant
        return


def _offer_latest(queue: asyncio.Queue[Any], event: Any) -> None:
    """Retain compatibility for bounded non-cursor queue callers."""
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


def _encode_delivery(epoch: str, delivery: LiveStreamDelivery) -> bytes:
    event_type = (
        f"{delivery.event.event_type}-snapshot"
        if delivery.snapshot and delivery.event.event_type != "source"
        else delivery.event.event_type
    )
    lines: list[str] = []
    if delivery.sequence is not None:
        lines.append(f"id: {epoch}:{delivery.sequence}")
    lines.append(f"event: {_field(event_type)}")
    if delivery.dropped_before > 0:
        lines.append(f"dropped: {delivery.dropped_before}")
    lines.append(f"data: {_json(delivery.event.payload)}")
    return ("\n".join(lines) + "\n\n").encode()


def _encode_event(event: LiveStreamEvent) -> bytes:
    return (
        f"id: {_field(event.event_id)}\nevent: {_field(event.event_type)}\n"
        f"data: {_json(event.payload)}\n\n"
    ).encode()


def _encode_legacy_delivery(delivery: LiveStreamDelivery) -> bytes:
    lines = [
        f"id: {_field(delivery.event.event_id)}",
        f"event: {_field(delivery.event.event_type)}",
    ]
    if delivery.dropped_before > 0:
        lines.append(f"dropped: {delivery.dropped_before}")
    lines.append(f"data: {_json(delivery.event.payload)}")
    return ("\n".join(lines) + "\n\n").encode()


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
    if len(encoded.encode("utf-8")) > _MAX_DATA_BYTES:
        raise ValueError("Live SSE payload exceeds the data size limit")
    return encoded.replace("\r", "\\r").replace("\n", "\\n")


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _last_event_cursor(request: Request) -> tuple[str | None, int | None]:
    raw = request.headers.get("last-event-id")
    if raw is None or raw == "":
        return None, None
    match = _CURSOR.fullmatch(raw)
    if match is None:
        raise ValueError("Last-Event-ID MUST be an Operator-issued stream cursor")
    return match.group("epoch"), int(match.group("sequence"))


__all__ = [
    "LiveStreamDelivery",
    "LiveStreamEvent",
    "LiveStreamHub",
    "make_live_stream_route",
]
