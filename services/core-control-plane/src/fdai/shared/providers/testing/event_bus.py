"""In-memory :class:`EventBus` with Kafka-style consumer-group offsets.

Semantics that matter for the safety-core tests:

- **Per-partition ordering** - one implicit partition (partition=0) so
  ordering-by-key equals ordering-by-publish. Real brokers preserve order
  only per partition; the fake keeps that guarantee trivially.
- **Consumer-group offsets** - each ``group_id`` remembers where its last
  ``subscribe(...)`` yield ended. A second call resumes from that offset.
  New groups start at offset 0 (mirrors ``auto.offset.reset=earliest``).
- **At-least-once delivery** - the fake never removes records; a consumer
  MUST enforce idempotency on the event's ``idempotency_key`` just like on
  a real broker.
- **DLQ convention** - ``dead_letter`` publishes into ``<topic>.dlq``,
  matching the wire-level rule in ``csp-neutrality.md § Event Bus``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from threading import Lock
from typing import Any

from fdai.shared.providers.event_bus import (
    EventBus,
    EventEnvelope,
    PublishReceipt,
)


class InMemoryEventBus(EventBus):
    """Dict-of-lists event bus with consumer-group semantics."""

    def __init__(self) -> None:
        self._records: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._offsets: dict[tuple[str, str], int] = {}  # (topic, group_id) → next offset
        self._lock = Lock()

    # ---- EventBus Protocol ---------------------------------------------------

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        with self._lock:
            queue = self._records.setdefault(topic, [])
            offset = len(queue)
            queue.append((key, deepcopy(dict(payload))))
            return PublishReceipt(topic=topic, partition=0, offset=offset)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        # Snapshot the queue at the moment subscribe() is called so a
        # concurrent publish doesn't extend our iterator mid-flight -
        # matching how real consumers poll a batch.
        with self._lock:
            queue_snapshot = list(self._records.get(topic, ()))
            start = self._offsets.get((topic, group_id), 0)

        for offset in range(start, len(queue_snapshot)):
            key, payload = queue_snapshot[offset]
            yield EventEnvelope(
                topic=topic,
                key=key,
                payload=deepcopy(payload),
                offset=offset,
            )
            with self._lock:
                # Advance the group's committed offset after each successful
                # yield. Consumer failure between yields → the next
                # subscribe() call resumes from the *last committed* offset.
                self._offsets[(topic, group_id)] = offset + 1

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        # Kafka has no native DLQ - enforce the <topic>.dlq convention.
        dlq_topic = f"{topic}.dlq"
        dlq_payload: dict[str, Any] = {
            "original_topic": topic,
            "reason": reason,
            "payload": deepcopy(dict(payload)),
        }
        with self._lock:
            self._records.setdefault(dlq_topic, []).append((key, dlq_payload))


__all__ = ["InMemoryEventBus"]
