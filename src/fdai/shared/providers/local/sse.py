"""Bounded process-local SSE fan-out adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fdai.shared.providers.sse import SseEvent, SseSink


class LocalSseSink(SseSink):
    """Fan out to bounded per-subscriber queues and retain no evidence."""

    def __init__(self, *, max_queue: int = 256) -> None:
        if max_queue < 1:
            raise ValueError("max_queue MUST be >= 1")
        self._max_queue = max_queue
        self._subscribers: dict[str, list[asyncio.Queue[SseEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: SseEvent) -> None:
        async with self._lock:
            queues = tuple(self._subscribers.get(channel, ()))
        for queue in queues:
            _offer(queue, event)

    def subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        return self._subscribe(channel)

    async def _subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subscribers.setdefault(channel, []).append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                bucket = self._subscribers.get(channel)
                if bucket is not None and queue in bucket:
                    bucket.remove(queue)
                    if not bucket:
                        self._subscribers.pop(channel, None)

    def subscriber_count(self, channel: str) -> int:
        return len(self._subscribers.get(channel, ()))


def _offer(queue: asyncio.Queue[SseEvent], event: SseEvent) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        queue.put_nowait(event)


__all__ = ["LocalSseSink"]
