"""Event bus - Kafka-wire by default; DI seam for alternates.

Async by contract - real Kafka clients pump a poll loop that is coroutine-
friendly, and Event Hubs / Redpanda / Confluent all expose native asyncio
integrations (`aiokafka`, `confluent-kafka`'s asyncio wrappers, etc.).

Realizes the wire-level contract in
``docs/roadmap/architecture/csp-neutrality.md § Event Bus Contract``.

Concrete implementations:

- **Upstream default** (Kafka against Event Hubs) lands with W1.4 / W6.3.
- **In-memory fake** (queue + consumer-group semantics) lands with W6.2.
- **Alternate substrates** (Redpanda, Confluent Cloud, AWS MSK) plug in
  under ``infra/modules/event-bus/`` and register a matching adapter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    """Broker-side acknowledgement of a published record.

    ``offset`` is ``None`` on backends that do not surface an offset (some
    lightweight in-memory fakes).
    """

    topic: str
    partition: int
    offset: int | None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """One record delivered by a subscriber."""

    topic: str
    key: str
    payload: Mapping[str, Any]
    offset: int | None


@runtime_checkable
class EventBus(Protocol):
    """Kafka-wire event bus (async)."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        """Publish one record, keyed for per-resource ordering.

        The Kafka contract preserves order per partition; the caller passes a
        stable ``key`` (typically the affected resource id) so ordering is
        per-resource, not global.
        """
        ...

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        """Return an :class:`AsyncIterator` yielding records for ``topic``.

        Each ``__anext__()`` awaits a poll; implementations decide the exact
        backoff. Consumer offsets are managed under ``group_id`` - at-least-
        once delivery is the guarantee, so the caller MUST enforce
        idempotency on the event's ``idempotency_key``.

        NOTE: this method is NOT itself async - it returns an async iterator
        so callers can drive the loop with ``async for envelope in
        bus.subscribe(topic, group)``.
        """
        ...

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        """Route a poison record to ``<topic>.dlq`` (or the equivalent).

        Kafka has no native DLQ; the contract mandates a ``<topic>.dlq``
        convention so behaviour is uniform across brokers.
        """
        ...


__all__ = ["EventBus", "EventEnvelope", "PublishReceipt"]
