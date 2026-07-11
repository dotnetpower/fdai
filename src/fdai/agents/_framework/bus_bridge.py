"""Bridge from pantheon dispatch to the ``EventBus`` provider Protocol.

The pantheon in-memory bus (:mod:`fdai.agents.bus`) is a
sync-dispatch tool that runs subscribers inline for tests. Production
runs against the real ``EventBus`` Protocol
(:class:`~fdai.shared.providers.event_bus.EventBus`) - Kafka-wire on
Event Hubs or an alternate broker.

This module gives the pantheon a Protocol-compatible bridge:

- :class:`EventBusBridge` accepts a `PantheonRegistry` + a real
  `EventBus` provider, enforces single-writer publish, injects
  ``producer_principal`` into every published payload, and exposes a
  ``run()`` coroutine that consumes registered subscribers via the
  provider's async iterator.

Idempotency: the pantheon agents already dedup on ``idempotency_key``;
the bridge does not add extra dedup. At-least-once delivery is the
underlying Kafka guarantee.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework.registry import PantheonRegistry
from fdai.agents._framework.topics import (
    ENVELOPE_SCHEMA_VERSION,
    MUTATION_TOPICS,
    OWNED_OBJECT_TOPICS,
    partition_key_for,
)
from fdai.shared.providers.event_bus import EventBus, PublishReceipt

_LOG = logging.getLogger(__name__)

Payload = Mapping[str, object]
Handler = Callable[[str, dict[str, object]], Awaitable[None]]


@dataclass
class BridgeMetrics:
    """Counters for pantheon bridge observability.

    Exposed via :meth:`EventBusBridge.snapshot` so Heimdall's health
    probe and the KPI collectors can read per-process delivery / failure
    rates without reaching into consumer internals.
    """

    consumers_started: int = 0
    consumers_crashed: int = 0
    consumers_restarted: int = 0
    consumers_gave_up: int = 0
    delivered: int = 0
    handler_errors: int = 0
    handler_retries: int = 0
    dead_lettered: int = 0
    dead_letter_errors: int = 0
    empty_partition_keys: int = 0
    published: int = 0
    publish_errors: int = 0
    missing_correlation_id: int = 0
    missing_idempotency_key: int = 0
    producer_principal_mismatch: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "consumers_started": self.consumers_started,
            "consumers_crashed": self.consumers_crashed,
            "consumers_restarted": self.consumers_restarted,
            "consumers_gave_up": self.consumers_gave_up,
            "delivered": self.delivered,
            "handler_errors": self.handler_errors,
            "handler_retries": self.handler_retries,
            "dead_lettered": self.dead_lettered,
            "dead_letter_errors": self.dead_letter_errors,
            "empty_partition_keys": self.empty_partition_keys,
            "published": self.published,
            "publish_errors": self.publish_errors,
            "missing_correlation_id": self.missing_correlation_id,
            "missing_idempotency_key": self.missing_idempotency_key,
            "producer_principal_mismatch": self.producer_principal_mismatch,
        }


def _warn_unknown_topic(topic: str, agent_name: str) -> None:
    """Warn when an ``object.*`` subscription targets an unregistered topic.

    A typo'd object topic (``object.verdit``) subscribes successfully but
    never receives a record - a silent dead seam. Non-object topics (the
    raw ingress topic, an alternate stream) are not pantheon object topics,
    so they are exempt from this check.
    """
    if topic.startswith("object.") and topic not in OWNED_OBJECT_TOPICS:
        _LOG.warning(
            "pantheon_subscribe_unknown_topic",
            extra={"topic": topic, "agent": agent_name},
        )


@dataclass
class EventBusBridge:
    """Adapter that lets pantheon agents talk to a real ``EventBus``.
    Substitute wherever tests use :class:`fdai.agents._framework.bus.InMemoryBus`
    at the composition root. The public surface intentionally mirrors
    :class:`InMemoryBus` so agent code stays unchanged.
    """

    provider: EventBus
    registry: PantheonRegistry
    consumer_group_prefix: str = "fdai-pantheon"
    max_consumer_restarts: int = 5
    restart_backoff_base: float = 0.5
    restart_backoff_max: float = 30.0
    shutdown_timeout: float = 5.0
    verify_producer_principal: bool = True
    handler_max_retries: int = 0
    handler_retry_backoff: float = 0.05
    _subs: dict[str, list[tuple[str, Handler]]] = field(default_factory=lambda: defaultdict(list))
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    metrics: BridgeMetrics = field(default_factory=BridgeMetrics)

    # ---- pantheon-style API --------------------------------------------

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        _warn_unknown_topic(topic, agent_name)
        existing = self._subs[topic]
        if any(name == agent_name and h == handler for name, h in existing):
            # A duplicate (topic, agent, handler) registration would spin up
            # a second consumer group and double-deliver every record to the
            # same handler. Skip it - the first registration stands.
            _LOG.warning(
                "pantheon_duplicate_subscription",
                extra={"topic": topic, "agent": agent_name},
            )
            return
        existing.append((agent_name, handler))

    def snapshot(self) -> dict[str, object]:
        """Return a health snapshot (metrics + live consumer count)."""
        live = sum(1 for t in self._tasks if not t.done())
        return {
            "subscriptions": sum(len(v) for v in self._subs.values()),
            "consumers_live": live,
            "metrics": self.metrics.as_dict(),
        }

    async def publish(
        self,
        principal: str,
        topic: str,
        payload: Payload,
    ) -> PublishReceipt:
        self.registry.assert_can_publish(principal, topic)
        enriched = dict(payload)
        enriched.setdefault("producer_principal", principal)
        # Stamp the envelope version so a rolling upgrade can gate on it.
        enriched.setdefault("schema_version", ENVELOPE_SCHEMA_VERSION)
        self._check_envelope(topic, enriched, principal)
        key = partition_key_for(topic, enriched)
        if not key:
            # An empty key collapses Kafka partitioning (loss of
            # per-resource ordering). Surface it rather than silently
            # round-robining the record.
            self.metrics.empty_partition_keys += 1
            _LOG.warning(
                "pantheon_empty_partition_key",
                extra={"topic": topic, "principal": principal},
            )
        try:
            receipt = await self.provider.publish(topic, key, enriched)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.metrics.publish_errors += 1
            _LOG.exception(
                "pantheon_publish_failed",
                extra={"topic": topic, "principal": principal},
            )
            raise
        self.metrics.published += 1
        return receipt

    def _check_envelope(self, topic: str, payload: Mapping[str, object], principal: str) -> None:
        """Count (never block) missing shared-envelope fields.

        The wire contract (agent-pantheon.md 6.1) says every message carries
        ``correlation_id`` and ``idempotency_key``. A missing field is a
        data-quality signal - it breaks correlation (tracing) or dedup
        (at-least-once safety) downstream - so it is counted and warned
        here rather than silently accepted. It is not a hard block: a bad
        envelope MUST NOT stall the pipeline, and the consumer side still
        fails toward safety.
        """
        if not str(payload.get("correlation_id", "")):
            self.metrics.missing_correlation_id += 1
            _LOG.warning(
                "pantheon_missing_correlation_id",
                extra={"topic": topic, "principal": principal},
            )
        # Only mutation topics strictly require an idempotency key (they
        # are the records an at-least-once redelivery could double-apply).
        if topic in MUTATION_TOPICS and not str(payload.get("idempotency_key", "")):
            self.metrics.missing_idempotency_key += 1
            _LOG.warning(
                "pantheon_missing_idempotency_key",
                extra={"topic": topic, "principal": principal},
            )

    # ---- consumer loop -------------------------------------------------

    async def run(self) -> None:
        """Start one background task per (topic, subscriber) pair.

        Each subscriber uses a distinct consumer group so multiple
        pantheon agents can consume the same topic without stealing each
        other's records (Kafka semantics: same group = load-balance;
        distinct group = fan-out).

        Blast-radius isolation: consumers are gathered with
        ``return_exceptions=True`` so a single crashed consumer never
        cancels its siblings. Each crash is counted and logged in
        :meth:`_consume`; this method surfaces only a summary.
        """
        if self._tasks:
            raise RuntimeError("EventBusBridge.run() is already running; call stop() first")
        for topic, subs in self._subs.items():
            for agent_name, handler in subs:
                group_id = f"{self.consumer_group_prefix}.{agent_name}"
                task = asyncio.create_task(
                    self._consume(topic=topic, group_id=group_id, handler=handler),
                    name=f"pantheon-consumer.{agent_name}.{topic}",
                )
                self._tasks.append(task)
        self.metrics.consumers_started = len(self._tasks)
        if not self._tasks:
            _LOG.info("pantheon_bridge_no_subscribers")
            return
        _LOG.info(
            "pantheon_bridge_started",
            extra={"consumers": len(self._tasks), "prefix": self.consumer_group_prefix},
        )
        try:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            crashed = 0
            for task, result in zip(self._tasks, results, strict=True):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    crashed += 1
                    # Log each crashing consumer distinctly so an operator
                    # can identify *which* topic wedged. A bare aggregate
                    # count buries the root cause under a summary.
                    _LOG.error(
                        "pantheon_bridge_consumer_crashed",
                        extra={
                            "task_name": task.get_name(),
                            "error_type": type(result).__name__,
                            "error": str(result),
                        },
                    )
            if crashed:
                _LOG.error(
                    "pantheon_bridge_consumers_crashed",
                    extra={"crashed": crashed, "total": len(results)},
                )
        finally:
            # Ensure no orphan tasks remain even if one crashes.
            await self.stop()

    async def stop(self) -> None:
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            # Bounded drain: a wedged consumer (e.g. a handler stuck in a
            # non-cancellable blocking call) MUST NOT hang process
            # shutdown. Cancelled tasks that do not settle within the
            # timeout are abandoned; they are already cancel-requested.
            await asyncio.wait(self._tasks, timeout=self.shutdown_timeout)
        self._tasks.clear()

    async def _consume(
        self,
        *,
        topic: str,
        group_id: str,
        handler: Handler,
    ) -> None:
        # Self-healing: a subscribe-loop crash restarts THIS consumer with
        # exponential backoff (blast-radius isolation keeps siblings
        # running; self-healing brings a crashed subscription back rather
        # than leaving it permanently dead). After max_consumer_restarts
        # the consumer gives up - counted + logged - without touching the
        # rest of the pantheon.
        attempt = 0
        while True:
            try:
                async for envelope in self.provider.subscribe(topic, group_id):
                    if not self._producer_authorized(topic, envelope.payload):
                        # Consumer-side single-writer check: a record whose
                        # producer_principal is not the topic owner is an
                        # impostor (a compromised or buggy producer that got
                        # past publish-side auth on another path). Do NOT
                        # hand it to a subscriber - route it to the DLQ and
                        # move on. Publish-side auth is not enough on its
                        # own: the consumer trusts the wire, so it must
                        # re-verify the wire.
                        await self._safe_dead_letter(
                            group_id=group_id,
                            topic=topic,
                            envelope=envelope,
                            reason=(
                                "producer_principal "
                                f"{envelope.payload.get('producer_principal')!r} "
                                f"is not the owner of {topic!r}"
                            ),
                        )
                        continue
                    try:
                        await self._deliver(topic, handler, envelope.payload)
                        self.metrics.delivered += 1
                        attempt = 0  # progress resets the backoff window
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - route to DLQ, keep loop alive
                        self.metrics.handler_errors += 1
                        _LOG.warning(
                            "pantheon_handler_error",
                            extra={
                                "group_id": group_id,
                                "topic": topic,
                                "offset": envelope.offset,
                                "error": str(exc),
                            },
                        )
                        await self._safe_dead_letter(
                            group_id=group_id,
                            topic=topic,
                            envelope=envelope,
                            reason=f"handler error: {exc}",
                        )
                # Iterator ended normally (finite in-memory drain): done.
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.consumers_crashed += 1
                attempt += 1
                if attempt > self.max_consumer_restarts:
                    self.metrics.consumers_gave_up += 1
                    _LOG.exception(
                        "pantheon_consumer_gave_up",
                        extra={
                            "group_id": group_id,
                            "topic": topic,
                            "attempts": attempt,
                        },
                    )
                    return
                backoff = min(
                    self.restart_backoff_base * (2 ** (attempt - 1)),
                    self.restart_backoff_max,
                )
                # Full jitter (AWS-style): spread simultaneous restarts so a
                # broker outage that crashes many consumers at once does not
                # produce a synchronized retry storm on recovery. Jitter is
                # non-security (retry timing, not entropy), so ``random`` is
                # fine.
                backoff = random.uniform(0.0, backoff)  # noqa: S311 - retry jitter, not crypto
                self.metrics.consumers_restarted += 1
                _LOG.warning(
                    "pantheon_consumer_restarting",
                    extra={
                        "group_id": group_id,
                        "topic": topic,
                        "attempt": attempt,
                        "backoff_s": backoff,
                    },
                )
                await asyncio.sleep(backoff)
                # loop: re-subscribe, resuming from the committed offset.

    def _producer_authorized(self, topic: str, payload: Payload) -> bool:
        """Consumer-side single-writer check.

        Returns ``True`` when the record may be delivered. A topic with no
        declared owner (the raw ingress topic, or an alternate stream) is
        not a pantheon object topic, so there is nothing to verify against -
        allow it. A record whose ``producer_principal`` is present but not
        the topic owner is an impostor and is rejected (counted). An absent
        principal is allowed (a legacy / external producer that did not go
        through the bridge) but the publish-side ``missing`` counters already
        make that visible.
        """
        if not self.verify_producer_principal:
            return True
        owner = self.registry.owner_of_topic(topic)
        if owner is None:
            return True
        principal = str(payload.get("producer_principal", ""))
        if principal and principal != owner:
            self.metrics.producer_principal_mismatch += 1
            _LOG.warning(
                "pantheon_producer_principal_mismatch",
                extra={"topic": topic, "principal": principal, "owner": owner},
            )
            return False
        return True

    async def _deliver(self, topic: str, handler: Handler, payload: Payload) -> None:
        """Invoke ``handler`` with bounded in-place retry before giving up.

        A transient handler failure (a brief backend blip) should not
        immediately dead-letter a good record. ``handler_max_retries``
        (default 0 - retry disabled) retries the handler with a short
        backoff; the final failure propagates so the caller routes it to
        the DLQ. Each retry is counted so retry pressure is observable.
        """
        last_exc: Exception
        for attempt in range(self.handler_max_retries + 1):
            try:
                await handler(topic, dict(payload))
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - retry then propagate to DLQ
                last_exc = exc
                if attempt < self.handler_max_retries:
                    self.metrics.handler_retries += 1
                    await asyncio.sleep(self.handler_retry_backoff * (2**attempt))
        # Loop exhausted without a successful return: re-raise the final
        # failure so the caller routes the record to the DLQ.
        raise last_exc

    async def _safe_dead_letter(
        self,
        *,
        group_id: str,
        topic: str,
        envelope: Any,
        reason: str,
    ) -> None:
        """Route a poison record to the DLQ, isolating DLQ failures.

        A broker hiccup on the DLQ path MUST NOT crash the consumer (that
        would turn one bad record into a dead subscription); it is
        counted and logged instead.
        """
        try:
            await self.provider.dead_letter(
                topic,
                envelope.key,
                envelope.payload,
                reason=reason,
            )
            self.metrics.dead_lettered += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self.metrics.dead_letter_errors += 1
            _LOG.exception(
                "pantheon_dead_letter_failed",
                extra={"group_id": group_id, "topic": topic},
            )


__all__ = ["EventBusBridge", "BridgeMetrics"]
