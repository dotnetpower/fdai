"""In-memory :class:`SseSink` - async fan-out queues, one per subscriber.

Late-join semantics: a subscriber that connects after ``publish()`` was
called MUST NOT see the earlier events (standard SSE / pub-sub). Callers
that need replay MUST persist elsewhere (audit log or Kafka topic) and
seed subscribers from that record.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fdai.shared.providers.sse import SseEvent, SseSink


class InMemorySseSink(SseSink):
    """Async fan-out to per-subscriber queues.

    ``max_queue`` (default ``None`` = unbounded) makes each subscriber
    queue a bounded ring: when it is full, :meth:`publish` drops the
    OLDEST event and keeps the newest, so a stalled consumer can never
    grow memory without bound (the production backpressure posture) while
    the live stream stays current. Unbounded remains the historical
    default for unit tests + debugger sessions.
    """

    def __init__(self, *, max_queue: int | None = None) -> None:
        if max_queue is not None and max_queue < 1:
            raise ValueError("max_queue MUST be >= 1 or None")
        # Per-channel list of live subscriber queues. Access under a lock
        # so publish() and subscribe() cannot race.
        self._max_queue = max_queue
        self._subscribers: dict[str, list[asyncio.Queue[SseEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: SseEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(channel, ()))
        for queue in queues:
            _offer(queue, event)

    def subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        return self._subscribe(channel)

    async def _subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=self._max_queue or 0)
        async with self._lock:
            self._subscribers.setdefault(channel, []).append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            # Detach on cancel / consumer break so leaked queues do not
            # accumulate memory over long sessions.
            async with self._lock:
                bucket = self._subscribers.get(channel)
                if bucket is not None:
                    try:
                        bucket.remove(queue)
                    except ValueError:
                        pass
                    if not bucket:
                        self._subscribers.pop(channel, None)

    # ---- Test helpers --------------------------------------------------------

    def subscriber_count(self, channel: str) -> int:
        """Return the number of subscribers currently attached to ``channel``."""
        return len(self._subscribers.get(channel, ()))


def _offer(queue: asyncio.Queue[SseEvent], event: SseEvent) -> None:
    """Enqueue ``event``, dropping the oldest on a full bounded queue.

    An unbounded queue never raises ``QueueFull``; a bounded one keeps the
    stream current (drop-oldest) rather than blocking the publisher.
    """
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


__all__ = ["InMemorySseSink"]
