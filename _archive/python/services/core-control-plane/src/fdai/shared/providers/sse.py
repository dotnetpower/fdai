"""SSE outbound-streaming seam.

Server-Sent Events (SSE, ``text/event-stream``) is the CSP-neutral
protocol for real-time server → client streaming that the console SPA,
ChatOps webhook consumers, and external audit-tail observers subscribe
to. Kafka handles internal machine-to-machine flow; SSE handles the
public read-only stream.

Async by contract (I/O over HTTP). Concrete implementations:

- **Upstream default (test/dev)** - :class:`InMemorySseSink` in
  ``shared/providers/testing/sse.py`` (fan-out queues).
- **HTTP server** - lands together with the console read-only surface
  after W1.4 telemetry is in place; the ASGI framework choice is a fork
  decision (FastAPI / Starlette / Litestar all speak SSE natively).

Wiring
------
Real-time updates ride the ``EventBus`` (internal Kafka) end and are
relayed to ``SseSink`` via
:class:`fdai.shared.streaming.SseBroadcaster`. Consumers therefore
subscribe to SSE by channel name (e.g. ``aw.audit.stream``), not to a
Kafka topic - the relay boundary is where cross-CSP portability meets
the browser.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SseEvent:
    """One event as it appears on the SSE wire.

    Fields map 1:1 to the SSE fields defined by the WHATWG HTML spec:

    - ``id``    → ``id:`` line (used for ``Last-Event-ID`` resume).
    - ``event`` → ``event:`` type (e.g. ``audit.entry.appended``).
    - ``data``  → ``data:`` payload (text; JSON-encode at the boundary).
    - ``retry_ms`` → ``retry:`` reconnect hint (milliseconds); optional.
    """

    id: str | None
    event: str
    data: str
    retry_ms: int | None = None


@runtime_checkable
class SseSink(Protocol):
    """Publish an event to every subscriber of ``channel``; subscribe from now on."""

    async def publish(self, channel: str, event: SseEvent) -> None:
        """Fan an :class:`SseEvent` out to every current subscriber of ``channel``.

        Semantics are pub/sub: a subscriber that joins after this call
        will NOT see this event - it starts from the next publish. This
        mirrors standard SSE behaviour where a fresh connection begins
        at the current stream tip.
        """
        ...

    def subscribe(self, channel: str) -> AsyncIterator[SseEvent]:
        """Yield events published to ``channel`` from the point of subscribe on.

        Cancellation-safe: on ``asyncio.CancelledError`` the implementation
        MUST detach the subscriber cleanly (no leaked queues).
        """
        ...


__all__ = ["SseEvent", "SseSink"]
