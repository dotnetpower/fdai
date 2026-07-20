"""Process-local EventBus adapter for the interactive development runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from copy import deepcopy
from typing import Any

from fdai.shared.providers.event_bus import EventBus, EventEnvelope, PublishReceipt


class LocalEventBus(EventBus):
    """Retain local records and serve blocking consumer-group subscriptions."""

    def __init__(self) -> None:
        self._records: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._offsets: dict[tuple[str, str], int] = {}
        self._conditions: dict[str, asyncio.Condition] = {}

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        condition = self._condition(topic)
        async with condition:
            queue = self._records.setdefault(topic, [])
            offset = len(queue)
            queue.append((key, deepcopy(dict(payload))))
            condition.notify_all()
        return PublishReceipt(topic=topic, partition=0, offset=offset)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        condition = self._condition(topic)
        group_key = (topic, group_id)
        while True:
            async with condition:
                offset = self._offsets.get(group_key, 0)
                while offset >= len(self._records.get(topic, ())):
                    await condition.wait()
                    offset = self._offsets.get(group_key, 0)
                key, payload = self._records[topic][offset]
            yield EventEnvelope(
                topic=topic,
                key=key,
                payload=deepcopy(payload),
                offset=offset,
            )
            self._offsets[group_key] = offset + 1

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


__all__ = ["LocalEventBus"]
