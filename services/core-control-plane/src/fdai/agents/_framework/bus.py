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

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fdai.agents._framework.registry import PantheonRegistry
from fdai.agents._framework.topics import (
    ENVELOPE_SCHEMA_VERSION,
    OWNED_OBJECT_TOPICS,
    missing_mutation_envelope_fields,
    partition_key_for,
)

_LOG = logging.getLogger(__name__)

Payload = dict[str, Any]
Handler = Callable[[str, Payload], Awaitable[None]]
PayloadValidator = Callable[[str, Payload], None]


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
    - it can run the same publish-side payload validator as the bridge,
    - it can simulate duplicate delivery for at-least-once idempotency tests,
    - it **isolates a raising subscriber** by default (one bad handler
      MUST NOT stop its siblings, exactly as the Kafka bridge routes a
      poison record to the DLQ and keeps the consumer alive). The failing
      delivery is captured in :attr:`dead_letters` for assertions. Set
      ``isolate_handlers=False`` to restore fail-fast propagation for a
      test that wants it.
    - it halts ordered mutation topics after a poison handler by default,
      matching the bridge's poison-halt semantics so a later mutation cannot
      overtake an earlier failed mutation in local tests.
    """

    registry: PantheonRegistry
    isolate_handlers: bool = True
    handler_timeout: float | None = 60.0
    handler_max_retries: int = 0
    handler_retry_backoff: float = 0.0
    halt_ordered_topic_on_poison: bool = True
    duplicate_delivery_count: int = 1
    payload_validator: PayloadValidator | None = None
    subscribers: dict[str, list[tuple[str, Handler]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    published: list[PublishedMessage] = field(default_factory=list)
    dead_letters: list[PublishedMessage] = field(default_factory=list)
    empty_partition_keys: int = 0
    handler_errors: int = 0
    handler_retries: int = 0
    ordered_poison_halts: int = 0
    schema_violations: int = 0
    duplicate_deliveries: int = 0
    _halted_topics: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.handler_max_retries < 0:
            raise ValueError("handler_max_retries MUST be >= 0")
        if self.duplicate_delivery_count < 1:
            raise ValueError("duplicate_delivery_count MUST be >= 1")

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        if topic.startswith("object.") and topic not in OWNED_OBJECT_TOPICS:
            _LOG.error(
                "inmemory_bus_subscribe_unknown_topic",
                extra={"topic": topic, "agent": agent_name},
            )
            raise ValueError(f"unknown pantheon object topic {topic!r} for agent {agent_name!r}")
        existing = self.subscribers[topic]
        if any(name == agent_name and h == handler for name, h in existing):
            _LOG.warning(
                "inmemory_bus_duplicate_subscription",
                extra={"topic": topic, "agent": agent_name},
            )
            return
        existing.append((agent_name, handler))

    async def publish(self, principal: str, topic: str, payload: Payload) -> None:
        if topic in self._halted_topics:
            raise RuntimeError(f"topic {topic!r} is halted after ordered poison")
        self.registry.assert_can_publish(principal, topic)
        enriched = dict(payload)
        enriched["producer_principal"] = principal
        enriched.setdefault("schema_version", ENVELOPE_SCHEMA_VERSION)
        enriched["envelope_schema_version"] = ENVELOPE_SCHEMA_VERSION
        missing = missing_mutation_envelope_fields(topic, enriched)
        if missing:
            fields = ", ".join(missing)
            raise ValueError(
                f"refusing to publish mutation topic {topic!r}: missing required "
                f"envelope field(s): {fields}"
            )
        if self.payload_validator is not None:
            try:
                self.payload_validator(topic, enriched)
            except Exception:
                self.schema_violations += 1
                raise
        key = partition_key_for(topic, enriched)
        if not key:
            self.empty_partition_keys += 1
        self.published.append(
            PublishedMessage(topic=topic, payload=dict(enriched), principal=principal, key=key)
        )
        for agent_name, handler in self.subscribers.get(topic, []):
            # Hand each subscriber its own copy so a handler that mutates the
            # payload cannot contaminate later subscribers or the caller's
            # object (the Kafka-backed bridge copies per delivery too).
            try:
                await self._deliver(topic, handler, enriched)
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
                if self.halt_ordered_topic_on_poison and topic in {
                    "object.action-run",
                    "object.rollback",
                }:
                    self.ordered_poison_halts += 1
                    self._halted_topics.add(topic)
                    break

    async def _deliver(self, topic: str, handler: Handler, payload: Payload) -> None:
        for duplicate_index in range(self.duplicate_delivery_count):
            if duplicate_index:
                self.duplicate_deliveries += 1
            last_exc: Exception | None = None
            for attempt in range(self.handler_max_retries + 1):
                try:
                    if self.handler_timeout is not None:
                        await asyncio.wait_for(handler(topic, dict(payload)), self.handler_timeout)
                    else:
                        await handler(topic, dict(payload))
                    break
                except Exception as exc:  # noqa: BLE001 - retry then isolate/propagate
                    last_exc = exc
                    if attempt < self.handler_max_retries:
                        self.handler_retries += 1
                        if self.handler_retry_backoff:
                            await asyncio.sleep(self.handler_retry_backoff * (2**attempt))
                        continue
                    raise last_exc from exc

    def clear_history(self) -> None:
        self.published.clear()
        self.dead_letters.clear()
        self.empty_partition_keys = 0
        self.handler_errors = 0
        self.handler_retries = 0
        self.ordered_poison_halts = 0
        self.schema_violations = 0
        self.duplicate_deliveries = 0
        self._halted_topics.clear()

    def messages_on(self, topic: str) -> list[PublishedMessage]:
        return [m for m in self.published if m.topic == topic]


__all__ = ["InMemoryBus", "PantheonBus", "PublishedMessage", "Payload", "Handler"]
