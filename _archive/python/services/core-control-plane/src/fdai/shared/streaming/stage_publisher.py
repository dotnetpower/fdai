"""Adapters that bridge :class:`StagePublisher` to concrete transports.

Two shipped implementations, both satisfying the
:class:`~fdai.shared.providers.stage_publisher.StagePublisher` Protocol:

- :class:`SseSinkStagePublisher` - fan out directly onto an
  :class:`~fdai.shared.providers.sse.SseSink`. Zero-hop in-process
  delivery, ideal for a single-replica Operator API + browser SPA. Also the
  path used by the local dev harness so nothing depends on a running
  Kafka.
- :class:`EventBusStagePublisher` - publish onto a Kafka topic so the
  existing :class:`~fdai.shared.streaming.broadcaster.SseBroadcaster`
  can fan out across replicas. This is the production path; a fork
  binds it at composition when it wants multi-replica live view without
  sticky routing.

Both preserve the "producer never blocks on a slow consumer" invariant
via the underlying sink / bus - the publisher itself only serializes
and hands off.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.sse import SseEvent, SseSink
from fdai.shared.providers.stage_publisher import StageEvent, StagePublisher

_LOGGER = logging.getLogger(__name__)


class SseSinkStagePublisher(StagePublisher):
    """Emit :class:`StageEvent` records as :class:`SseEvent` on one
    :class:`SseSink` channel.

    The wire encoding is a single JSON object per SSE ``data:`` field
    (compact separators) matching the audit table + live tile format.
    The SSE ``id`` is set to ``event_id`` so browsers get correct
    ``Last-Event-ID`` on reconnect.
    """

    def __init__(
        self,
        sink: SseSink,
        *,
        channel: str,
        event_type: str = "stage",
    ) -> None:
        if not channel:
            raise ValueError("SseSinkStagePublisher.channel MUST be non-empty")
        self._sink = sink
        self._channel = channel
        self._event_type = event_type

    async def emit(self, event: StageEvent) -> None:
        payload = json.dumps(event.to_dict(), separators=(",", ":"))
        try:
            await self._sink.publish(
                self._channel,
                SseEvent(id=event.event_id, event=self._event_type, data=payload),
            )
        except Exception:  # noqa: BLE001 - a slow / failing sink MUST NOT abort the pipeline
            _LOGGER.debug("sse_stage_publish_failed", exc_info=True)


class EventBusStagePublisher(StagePublisher):
    """Emit :class:`StageEvent` records onto a Kafka topic for
    :class:`~fdai.shared.streaming.broadcaster.SseBroadcaster` to relay.

    The bus key defaults to the driving event's ``event_id`` so records
    for the same event land on the same partition and stay ordered
    (Kafka guarantees per-partition ordering only). A fork MAY override
    the key strategy - for example, keying on ``correlation_id`` when
    live-view ordering across a whole incident is more important than
    per-idempotency-key ordering.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        topic: str,
        key_selector: Callable[[StageEvent], str] | None = None,
    ) -> None:
        if not topic:
            raise ValueError("EventBusStagePublisher.topic MUST be non-empty")
        self._bus = bus
        self._topic = topic
        self._key = key_selector or (lambda e: e.event_id)

    async def emit(self, event: StageEvent) -> None:
        try:
            await self._bus.publish(
                topic=self._topic,
                key=self._key(event),
                payload=event.to_dict(),
            )
        except Exception:  # noqa: BLE001 - a broker outage MUST NOT abort the pipeline
            _LOGGER.debug("event_bus_stage_publish_failed", exc_info=True)


__all__ = [
    "EventBusStagePublisher",
    "SseSinkStagePublisher",
]
