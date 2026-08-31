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

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

_LOGGER = logging.getLogger(__name__)


class EventPublishNotAttemptedError(RuntimeError):
    """A publish failed before any byte of the record could reach the broker.

    Publishing has three outcomes, not two: acknowledged, provably not sent,
    and unknown. A caller that owns a duplicate-suppression claim may retry
    only the provable case, because a timeout, a dropped connection, or a
    broker error raised after the record left the client MAY still have been
    accepted.

    An adapter raises this ONLY when the failure happened strictly before the
    send - producer acquisition, authentication setup, or payload encoding.
    Every other failure MUST propagate as its own exception so the caller
    treats it as uncertain and reconciles it before republishing.
    """


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

        Raises:
            EventPublishNotAttemptedError: the record provably never reached the
                transport, so a caller MAY retry it without reconciliation.
                Any other exception leaves the outcome unknown.
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


@asynccontextmanager
async def subscription(
    bus: EventBus,
    topic: str,
    group_id: str,
) -> AsyncIterator[AsyncIterator[EventEnvelope]]:
    """Iterate a subscription and close it inside the consumer's own task.

    A plain ``async for`` does not close the underlying async generator when
    the frame unwinds, so an adapter that tears the broker connection down in
    its ``finally`` would run that teardown during interpreter finalization -
    after asyncio has already cancelled the client's internal tasks. Every
    consumer MUST drive its subscription through this helper.

    Teardown normally runs while an exception is in flight, and on shutdown that
    exception is ``CancelledError``. A failing broker teardown MUST NOT replace
    it: a supervisor that branches on ``Task.cancelled()`` would then report a
    cancelled consumer as a crashed one. The failure is logged against its topic
    and consumer group instead. Teardown after a clean exit still propagates.
    """

    stream = bus.subscribe(topic, group_id)
    try:
        yield stream
    except BaseException:
        await _close_quietly(stream, topic=topic, group_id=group_id)
        raise
    else:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()


async def _close_quietly(
    stream: AsyncIterator[EventEnvelope],
    *,
    topic: str,
    group_id: str,
) -> None:
    """Close a subscription without letting its failure mask the live exception."""

    aclose = getattr(stream, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the in-flight exception owns the outcome
        _LOGGER.warning(
            "event_bus_subscription_close_failed",
            extra={"topic": topic, "consumer_group": group_id},
            exc_info=True,
        )


__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventPublishNotAttemptedError",
    "PublishReceipt",
    "subscription",
]
