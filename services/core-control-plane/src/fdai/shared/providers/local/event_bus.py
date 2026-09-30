"""Process-local EventBus adapter for the interactive development runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from typing import Any

from fdai.shared.providers.event_bus import EventBus, EventEnvelope, PublishReceipt


class LocalEventBus(EventBus):
    """Retain local records and serve blocking consumer-group subscriptions.

    Retention uses absolute offsets and a per-topic size bound. Up to
    ``max_records_per_topic`` records stay replayable, so a consumer group that
    joins later starts from the oldest retained record, as with broker
    retention. Beyond the bound the oldest records are compacted, but never a
    record that a subscribed consumer group has not consumed yet; a lagging
    group therefore delays compaction instead of losing records.
    """

    def __init__(self, *, max_records_per_topic: int = 10_000) -> None:
        if max_records_per_topic < 1:
            raise ValueError("max_records_per_topic MUST be >= 1")
        self._records: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._base_offsets: dict[str, int] = {}
        self._offsets: dict[tuple[str, str], int] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._group_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._max_records_per_topic = max_records_per_topic

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        condition = self._condition(topic)
        async with condition:
            queue = self._records.setdefault(topic, [])
            offset = self._base_offsets.get(topic, 0) + len(queue)
            queue.append((key, deepcopy(dict(payload))))
            self._compact_locked(topic)
            condition.notify_all()
        return PublishReceipt(topic=topic, partition=0, offset=offset)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        # Register the group before the first poll so compaction already
        # protects records it has not consumed.
        self._offsets.setdefault((topic, group_id), self._base_offsets.get(topic, 0))
        return self._subscribe(topic, group_id)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        condition = self._condition(topic)
        group_key = (topic, group_id)
        group_lock = self._group_lock(group_key)
        self._offsets.setdefault(group_key, self._base_offsets.get(topic, 0))
        while True:
            async with group_lock:
                async with condition:
                    offset = self._offsets.get(group_key, 0)
                    while offset >= self._base_offsets.get(topic, 0) + len(
                        self._records.get(topic, ())
                    ):
                        await condition.wait()
                        offset = self._offsets.get(group_key, 0)
                    base_offset = self._base_offsets.get(topic, 0)
                    key, payload = self._records[topic][offset - base_offset]
                yield EventEnvelope(
                    topic=topic,
                    key=key,
                    payload=deepcopy(payload),
                    offset=offset,
                )
                async with condition:
                    self._offsets[group_key] = offset + 1
                    self._compact_locked(topic)

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        await self.publish(
            f"{topic}.dlq",
            key,
            {
                "original_topic": topic,
                "reason": reason,
                "payload": deepcopy(dict(payload)),
            },
        )

    def _condition(self, topic: str) -> asyncio.Condition:
        condition = self._conditions.get(topic)
        if condition is None:
            condition = asyncio.Condition()
            self._conditions[topic] = condition
        return condition

    def _group_lock(self, group_key: tuple[str, str]) -> asyncio.Lock:
        lock = self._group_locks.get(group_key)
        if lock is None:
            lock = asyncio.Lock()
            self._group_locks[group_key] = lock
        return lock

    def _compact_locked(self, topic: str) -> None:
        records = self._records.get(topic)
        if not records:
            return
        excess = len(records) - self._max_records_per_topic
        if excess <= 0:
            return
        base = self._base_offsets.get(topic, 0)
        drop_before = base + excess
        group_offsets = [
            offset
            for (offset_topic, _group), offset in self._offsets.items()
            if offset_topic == topic
        ]
        if group_offsets:
            drop_before = min(drop_before, min(group_offsets))
        drop_count = max(0, min(drop_before - base, len(records)))
        if drop_count:
            del records[:drop_count]
            self._base_offsets[topic] = base + drop_count


__all__ = ["LocalEventBus"]
