"""``SseBroadcaster`` - relay events from the internal ``EventBus`` to ``SseSink``.

The internal Kafka event bus carries machine-to-machine records. The
outbound SSE stream carries a redacted, JSON-encoded view of the same
records for browser / webhook consumers. This class is the boundary.

Design
------
- Every ``(topic, channel)`` pair is served by one background async task.
- Each task drives an ``async for envelope in event_bus.subscribe(topic,
  group_id)`` loop and calls ``await sse_sink.publish(channel, SseEvent
  (...))``.
- Cancellation is cooperative: :meth:`stop` cancels every task and
  awaits them; :meth:`run` is idempotent (calling it twice is a no-op
  on the second call).
- The broadcaster **never persists** anything; if a consumer disconnects
  mid-relay, later publishes are simply not delivered to that consumer.
  Persistent replay is the audit log's responsibility.

Wiring reference (planned)
--------------------------
- ``core/audit`` → ``aw.audit.stream`` SSE channel (audit log tail)
- ``core/risk_gate`` → ``aw.hil.queue`` SSE channel (HIL updates)
- ``core/tiers/*`` → ``aw.tier.decisions`` SSE channel (KPI dashboard)

The concrete map is a composition-root decision - this module only
supplies the mechanism.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fdai.shared.providers.event_bus import EventBus, EventEnvelope
from fdai.shared.providers.sse import SseEvent, SseSink

_LOGGER = logging.getLogger(__name__)

# An SSE `id:` derived from an untrusted event payload is stripped of CR/LF
# (SSE line terminators) and length-capped at the trust boundary so a
# hostile correlation_id cannot smuggle SSE fields downstream.
_MAX_ID_CHARS = 512


class SseBroadcaster:
    """Relay :class:`EventBus` topics to :class:`SseSink` channels."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        sse_sink: SseSink,
        topic_channel_map: Mapping[str, str],
        event_type: str = "envelope",
        group_id_prefix: str = "fdai-sse",
        retry_backoff_seconds: float = 1.0,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not topic_channel_map:
            raise ValueError("topic_channel_map MUST NOT be empty")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds MUST be >= 0")
        self._event_bus = event_bus
        self._sse_sink = sse_sink
        self._topic_channel_map = dict(topic_channel_map)
        self._event_type = event_type
        self._group_id_prefix = group_id_prefix
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._stopped = False

    async def run(self) -> None:
        """Start one relay task per topic → channel mapping.

        Idempotent - a second call before :meth:`stop` is a no-op. Once
        :meth:`stop` runs, the broadcaster is spent and MUST be
        re-instantiated.
        """
        # `_stopped` MUST be checked before `_started` - the flags are set in
        # the order (run -> _started=True, stop -> _stopped=True), so a
        # `run() -> stop() -> run()` sequence otherwise short-circuits on
        # `_started=True` and silently returns, making the RuntimeError guard
        # unreachable. Deny-first ordering keeps the "spent broadcaster"
        # contract honest.
        if self._stopped:
            raise RuntimeError("broadcaster already stopped; instantiate a new one")
        if self._started:
            return
        self._started = True

        loop = asyncio.get_running_loop()
        for topic, channel in self._topic_channel_map.items():
            group_id = f"{self._group_id_prefix}-{channel}"
            self._tasks.append(
                loop.create_task(
                    self._relay_topic(topic, channel, group_id),
                    name=f"sse-relay:{topic}->{channel}",
                )
            )

    async def stop(self) -> None:
        """Cancel every relay task and wait for cleanup. Idempotent."""
        if self._stopped:
            return
        self._stopped = True

        for task in self._tasks:
            task.cancel()
        # Await every task so their `finally` blocks (queue detach in the
        # in-memory fake, connection close in a real Kafka client) run.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _relay_topic(self, topic: str, channel: str, group_id: str) -> None:
        # A transient backend error MUST NOT permanently silence a channel:
        # log it and re-subscribe after a bounded backoff. Cancellation
        # (via ``stop``) breaks the retry loop cleanly. A normal end of the
        # subscription (generator exhausted) returns.
        while True:
            try:
                async for envelope in self._event_bus.subscribe(topic, group_id):
                    await self._sse_sink.publish(channel, self._envelope_to_sse(envelope))
                return
            except asyncio.CancelledError:
                _LOGGER.debug("sse-relay:%s->%s cancelled", topic, channel)
                raise
            except Exception:
                _LOGGER.warning(
                    "sse-relay:%s->%s error; retrying after %ss",
                    topic,
                    channel,
                    self._retry_backoff_seconds,
                    exc_info=True,
                )
                await self._sleeper(self._retry_backoff_seconds)

    def _envelope_to_sse(self, envelope: EventEnvelope) -> SseEvent:
        # Correlation id is optional; every audit-linked event carries it.
        correlation_id = _extract_correlation_id(envelope.payload)
        return SseEvent(
            id=correlation_id or _extract_event_id(envelope.payload),
            event=self._event_type,
            data=json.dumps(
                {
                    "topic": envelope.topic,
                    "key": envelope.key,
                    "offset": envelope.offset,
                    "payload": envelope.payload,
                },
                ensure_ascii=True,
                default=str,
            ),
        )


def _extract_correlation_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("correlation_id")
    return _sanitize_id(value) if isinstance(value, str) else None


def _extract_event_id(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("event_id")
    return _sanitize_id(value) if isinstance(value, str) else None


def _sanitize_id(value: str) -> str | None:
    """Trust-boundary clean of a payload-derived SSE id (no CR/LF, capped)."""
    flattened = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()
    if not flattened:
        return None
    return flattened[:_MAX_ID_CHARS]


__all__ = ["SseBroadcaster"]
