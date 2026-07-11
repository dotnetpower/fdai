"""In-memory pub/sub bus for tests and single-process runs.

Real deployment wraps this contract around a Kafka client (Event Hubs
on `:9093`). The in-memory implementation shipping here exists so:

- Wave 2 through 8 code can be exercised end-to-end without an external
  broker.
- Fork maintainers can develop against a deterministic bus before
  integrating their Azure adapter.

The bus enforces the single-writer invariant at publish time by
delegating to :class:`fdai.agents._framework.registry.PantheonRegistry`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fdai.agents._framework.registry import PantheonRegistry
from fdai.agents._framework.topics import (
    ENVELOPE_SCHEMA_VERSION,
    OWNED_OBJECT_TOPICS,
    partition_key_for,
)

_LOG = logging.getLogger(__name__)

Payload = dict[str, Any]
Handler = Callable[[str, Payload], Awaitable[None]]


@runtime_checkable
class PantheonBus(Protocol):
    """Structural bus contract the pantheon agents depend on.

    Both the sync-dispatch :class:`InMemoryBus` (tests / single-process
    runs) and the Kafka-backed
    :class:`fdai.agents._framework.bus_bridge.EventBusBridge` (production Event Hubs)
    satisfy this Protocol, so an agent binds to either without knowing
    which. Agents type their ``bus`` seam against this, never against the
    concrete test double - see the composition-root wiring in
    :mod:`fdai.agents.runtime`.
    """

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        """Register ``handler`` for every record published to ``topic``."""
        ...

    async def publish(self, principal: str, topic: str, payload: Payload) -> Any:
        """Publish ``payload`` to ``topic`` as ``principal`` (single-writer)."""
        ...


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    topic: str
    payload: Payload
    principal: str
    key: str = ""


@dataclass
class InMemoryBus:
    """Sync-dispatch pub/sub bus for tests.

    Publish delivers to every subscriber synchronously (await in order
    of subscription). This is intentional: tests rely on the entire
    reaction chain resolving before the publish returns.

    The bus mirrors the production
    :class:`~fdai.agents._framework.bus_bridge.EventBusBridge` on the
    details that a test could otherwise silently diverge on:

    - it injects ``producer_principal`` and ``schema_version`` into every
      payload (so a test sees the same enriched envelope prod would),
    - it computes the canonical partition key and counts empty keys,
    - it **isolates a raising subscriber** by default (one bad handler
      MUST NOT stop its siblings, exactly as the Kafka bridge routes a
      poison record to the DLQ and keeps the consumer alive). The failing
      delivery is captured in :attr:`dead_letters` for assertions. Set
      ``isolate_handlers=False`` to restore fail-fast propagation for a
      test that wants it.
    """

    registry: PantheonRegistry
    isolate_handlers: bool = True
    subscribers: dict[str, list[tuple[str, Handler]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    published: list[PublishedMessage] = field(default_factory=list)
    dead_letters: list[PublishedMessage] = field(default_factory=list)
    empty_partition_keys: int = 0
    handler_errors: int = 0

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        if topic.startswith("object.") and topic not in OWNED_OBJECT_TOPICS:
            # A typo'd object topic subscribes but never receives - a silent
            # dead seam. Warn (mirrors the production bridge).
            _LOG.warning(
                "inmemory_bus_subscribe_unknown_topic",
                extra={"topic": topic, "agent": agent_name},
            )
        existing = self.subscribers[topic]
        if any(name == agent_name and h == handler for name, h in existing):
            _LOG.warning(
                "inmemory_bus_duplicate_subscription",
                extra={"topic": topic, "agent": agent_name},
            )
            return
        existing.append((agent_name, handler))

    async def publish(self, principal: str, topic: str, payload: Payload) -> None:
        self.registry.assert_can_publish(principal, topic)
        enriched = dict(payload)
        enriched.setdefault("producer_principal", principal)
        enriched.setdefault("schema_version", ENVELOPE_SCHEMA_VERSION)
        key = partition_key_for(topic, enriched)
        if not key:
            self.empty_partition_keys += 1
        self.published.append(
            PublishedMessage(
                topic=topic, payload=dict(enriched), principal=principal, key=key
            )
        )
        for agent_name, handler in self.subscribers.get(topic, []):
            # Hand each subscriber its own copy so a handler that mutates the
            # payload cannot contaminate later subscribers or the caller's
            # object (the Kafka-backed bridge copies per delivery too).
            try:
                await handler(topic, dict(enriched))
            except Exception as exc:  # noqa: BLE001 - isolation mirrors the bridge DLQ
                self.handler_errors += 1
                if not self.isolate_handlers:
                    raise
                _LOG.warning(
                    "inmemory_bus_handler_error",
                    extra={
                        "topic": topic,
                        "subscriber": agent_name,
                        "error_type": type(exc).__name__,
                    },
                )
                self.dead_letters.append(
                    PublishedMessage(
                        topic=topic, payload=dict(enriched), principal=agent_name, key=key
                    )
                )

    def clear_history(self) -> None:
        self.published.clear()
        self.dead_letters.clear()
        self.empty_partition_keys = 0
        self.handler_errors = 0

    def messages_on(self, topic: str) -> list[PublishedMessage]:
        return [m for m in self.published if m.topic == topic]


__all__ = ["InMemoryBus", "PantheonBus", "PublishedMessage", "Payload", "Handler"]
