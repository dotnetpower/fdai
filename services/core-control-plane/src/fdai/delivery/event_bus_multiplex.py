"""Logical-topic multiplexing over one physical EventBus topic."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai_service_contracts.semantic_turn import (
    LOGICAL_TOPIC_FIELD,
    multiplexed_consumer_group,
)

from fdai.shared.providers.event_bus import (
    EventBus,
    EventEnvelope,
    PublishReceipt,
    subscription,
)


@dataclass(slots=True)
class MultiplexedEventBus:
    """Route a bounded logical topic set through one physical broker topic.

    Default subscription mode is intentionally unchanged: each logical topic
    derives its existing distinct physical consumer group with
    ``multiplexed_consumer_group(group_id, topic)``. Deployments that opt in to
    ``per_agent_consumer_groups`` use one distinct physical group per original
    agent group and route logical topics in process. That mode preserves broker
    ordering for the single physical stream and halts all logical delivery if a
    poison physical record blocks the shared consumer; use it only where the
    logical subscribers for an agent can share those semantics.
    """

    bus: EventBus
    logical_topics: frozenset[str]
    physical_topic: str
    per_agent_consumer_groups: bool = False
    _routes: dict[tuple[str, str], asyncio.Queue[EventEnvelope]] = field(
        default_factory=dict,
        init=False,
    )
    _pumps: dict[str, asyncio.Task[None]] = field(default_factory=dict, init=False)

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
            async with subscription(self.bus, physical_dlq, routed_group) as stream:
                async for envelope in stream:
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
            async with subscription(self.bus, topic, group_id) as stream:
                async for envelope in stream:
                    yield envelope
            return
        if self.per_agent_consumer_groups:
            routed_group = per_agent_multiplexed_consumer_group(group_id)
            queue = self._routes.setdefault((routed_group, topic), asyncio.Queue(maxsize=1_000))
            self._ensure_pump(routed_group)
            while True:
                yield await queue.get()
            return
        routed_group = multiplexed_consumer_group(group_id, topic)
        async with subscription(self.bus, self.physical_topic, routed_group) as stream:
            async for envelope in stream:
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
        if self.per_agent_consumer_groups and topic in self.logical_topics:
            routed_group = per_agent_multiplexed_consumer_group(group_id)
            self._routes.setdefault((routed_group, topic), asyncio.Queue(maxsize=1_000))
        return self._subscribe(topic, group_id)

    async def close(self) -> None:
        """Close the underlying broker adapter when it owns a lifecycle."""
        for task in self._pumps.values():
            task.cancel()
        if self._pumps:
            await asyncio.gather(*self._pumps.values(), return_exceptions=True)
            self._pumps.clear()
        close = getattr(self.bus, "close", None)
        if callable(close):
            await close()

    def _ensure_pump(self, routed_group: str) -> None:
        task = self._pumps.get(routed_group)
        if task is None or task.done():
            self._pumps[routed_group] = asyncio.create_task(
                self._pump_physical(routed_group),
                name=f"event-bus-multiplex.{routed_group}",
            )

    async def _pump_physical(self, routed_group: str) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            async with subscription(self.bus, self.physical_topic, routed_group) as stream:
                async for envelope in stream:
                    topic = envelope.payload.get(LOGICAL_TOPIC_FIELD)
                    if topic not in self.logical_topics:
                        continue
                    queue = self._routes.get((routed_group, str(topic)))
                    if queue is None:
                        continue
                    payload = dict(envelope.payload)
                    payload.pop(LOGICAL_TOPIC_FIELD, None)
                    await queue.put(
                        EventEnvelope(
                            topic=str(topic),
                            key=envelope.key,
                            payload=payload,
                            offset=envelope.offset,
                        )
                    )


def per_agent_multiplexed_consumer_group(group_id: str) -> str:
    """Derive the opt-in physical group for one agent-level logical group.

    The suffix is intentionally different from
    :func:`multiplexed_consumer_group`, whose topic-hash suffix is already
    deployed. Existing offsets therefore remain untouched unless a deployment
    explicitly enables this mode.
    """
    group_hash = hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:12]
    return f"{group_id}.all-logical.{group_hash}"


__all__ = ["MultiplexedEventBus", "per_agent_multiplexed_consumer_group"]
