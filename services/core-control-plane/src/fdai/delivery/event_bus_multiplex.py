"""Logical-topic multiplexing over one physical EventBus topic."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from fdai_service_contracts.semantic_turn import (
    LOGICAL_TOPIC_FIELD,
    multiplexed_consumer_group,
)

from fdai.shared.providers.event_bus import EventBus, EventEnvelope, PublishReceipt


@dataclass(frozen=True, slots=True)
class MultiplexedEventBus:
    """Route a bounded logical topic set through one physical broker topic."""

    bus: EventBus
    logical_topics: frozenset[str]
    physical_topic: str

    def __post_init__(self) -> None:
        if not self.logical_topics or not self.physical_topic:
            raise ValueError("logical_topics and physical_topic MUST be configured")

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if topic not in self.logical_topics:
            return await self.bus.publish(topic, key, payload)
        enriched = dict(payload)
        enriched[LOGICAL_TOPIC_FIELD] = topic
        receipt = await self.bus.publish(self.physical_topic, key, enriched)
        return PublishReceipt(topic=topic, partition=receipt.partition, offset=receipt.offset)

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        if topic not in self.logical_topics:
            await self.bus.dead_letter(topic, key, payload, reason)
            return
        enriched = dict(payload)
        enriched[LOGICAL_TOPIC_FIELD] = topic
        await self.bus.dead_letter(self.physical_topic, key, enriched, reason)

    async def _subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        logical_dlq_source = topic.removesuffix(".dlq") if topic.endswith(".dlq") else None
        if logical_dlq_source in self.logical_topics:
            routed_group = multiplexed_consumer_group(group_id, topic)
            physical_dlq = f"{self.physical_topic}.dlq"
            async for envelope in self.bus.subscribe(physical_dlq, routed_group):
                wrapped = dict(envelope.payload)
                original = wrapped.get("payload")
                if not isinstance(original, Mapping):
                    continue
                logical_payload = dict(original)
                if logical_payload.get(LOGICAL_TOPIC_FIELD) != logical_dlq_source:
                    continue
                logical_payload.pop(LOGICAL_TOPIC_FIELD, None)
                wrapped["original_topic"] = logical_dlq_source
                wrapped["payload"] = logical_payload
                yield EventEnvelope(
                    topic=topic,
                    key=envelope.key,
                    payload=wrapped,
                    offset=envelope.offset,
                )
            return
        if topic not in self.logical_topics:
            async for envelope in self.bus.subscribe(topic, group_id):
                yield envelope
            return
        routed_group = multiplexed_consumer_group(group_id, topic)
        async for envelope in self.bus.subscribe(self.physical_topic, routed_group):
            if envelope.payload.get(LOGICAL_TOPIC_FIELD) != topic:
                continue
            payload = dict(envelope.payload)
            payload.pop(LOGICAL_TOPIC_FIELD, None)
            yield EventEnvelope(
                topic=topic,
                key=envelope.key,
                payload=payload,
                offset=envelope.offset,
            )

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self._subscribe(topic, group_id)

    async def close(self) -> None:
        """Close the underlying broker adapter when it owns a lifecycle."""
        close = getattr(self.bus, "close", None)
        if callable(close):
            await close()


__all__ = ["MultiplexedEventBus"]
