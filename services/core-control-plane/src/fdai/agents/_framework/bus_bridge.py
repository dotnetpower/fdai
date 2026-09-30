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

from fdai.agents._framework.bus_bridge_observer import (
    AgentHandlerObserver,
    AgentHandlerPhase,
    notify_handler_observer,
)
from fdai.agents._framework.bus_metrics import BridgeMetrics
from fdai.agents._framework.bus_poison_halt import (
    clear_ordered_halt,
    is_ordered_halted,
    persist_ordered_halt,
)
from fdai.agents._framework.registry import PantheonRegistry
from fdai.agents._framework.topics import (
    ENVELOPE_SCHEMA_VERSION,
    MUTATION_TOPICS,
    OWNED_OBJECT_TOPICS,
    missing_mutation_envelope_fields,
    normalize_owned_object_envelope,
    partition_key_for,
)
from fdai.shared.providers.event_bus import EventBus, PublishReceipt
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)

Payload = Mapping[str, object]
Handler = Callable[[str, dict[str, object]], Awaitable[None]]
PayloadValidator = Callable[[str, Mapping[str, object]], None]
ConsumerStateObserver = Callable[[str, str, str], None]
"""Optional publish-side contract check (topic, payload) -> None; raises on
an invalid payload. Wire a ContractValidator-backed callable here to reject
a malformed record at the publish boundary (fail closed)."""


def _assert_known_topic(topic: str, agent_name: str) -> None:
    """Reject an ``object.*`` subscription targeting an unregistered topic.

    A typo'd object topic (``object.verdit``) subscribes successfully but
    never receives a record - a silent dead seam. Non-object topics (the
    raw ingress topic, an alternate stream) are not pantheon object topics,
    so they are exempt from this check.
    """
    if topic.startswith("object.") and topic not in OWNED_OBJECT_TOPICS:
        _LOG.error(
            "pantheon_subscribe_unknown_topic",
            extra={"topic": topic, "agent": agent_name},
        )
        raise ValueError(f"unknown pantheon object topic {topic!r} for agent {agent_name!r}")


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
    handler_max_retries: int = 0
    handler_retry_backoff: float = 0.05
    halt_ordered_topic_on_poison: bool = True
    handler_timeout: float | None = 60.0
    handler_timeouts: Mapping[str, float | None] = field(default_factory=dict)
    handler_observer_timeout: float | None = 1.0
    dead_letter_max_retries: int = 2
    dead_letter_retry_backoff: float = 0.25
    dead_letter_timeout: float | None = 5.0
    payload_validator: PayloadValidator | None = None
    handler_observer: AgentHandlerObserver | None = None
    consumer_state_observer: ConsumerStateObserver | None = None
    halt_state_store: StateStore | None = None
    _subs: dict[str, list[tuple[str, Handler]]] = field(default_factory=lambda: defaultdict(list))
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _consumer_states: dict[str, str] = field(default_factory=dict)
    _consumer_delivery_counts: dict[str, int] = field(default_factory=dict)
    _consumer_last_delivery_at: dict[str, float] = field(default_factory=dict)
    _handler_observer_failures: dict[tuple[str, str, AgentHandlerPhase], int] = field(
        default_factory=dict
    )
    metrics: BridgeMetrics = field(default_factory=BridgeMetrics)

    # ---- pantheon-style API --------------------------------------------

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        _assert_known_topic(topic, agent_name)
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
        terminal_states = {"gave_up", "halted"}
        unavailable_agents = sorted(
            {
                consumer_id.split(":", 1)[0]
                for consumer_id, state in self._consumer_states.items()
                if state in terminal_states
            }
        )
        return {
            "subscriptions": sum(len(v) for v in self._subs.values()),
            "consumers_live": live,
            "consumer_states": dict(sorted(self._consumer_states.items())),
            "consumer_deliveries": dict(sorted(self._consumer_delivery_counts.items())),
            "consumer_last_delivery_at": dict(sorted(self._consumer_last_delivery_at.items())),
            "unavailable_agents": unavailable_agents,
            "status": "degraded" if unavailable_agents else "healthy",
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
        enriched["producer_principal"] = principal
        # Keep a domain contract's schema_version intact. The transport
        # version has its own field so a rolling upgrade cannot rewrite a
        # payload such as ForecastOutcome schema "1.0.0" into integer 1.
        enriched.setdefault("schema_version", ENVELOPE_SCHEMA_VERSION)
        enriched["envelope_schema_version"] = ENVELOPE_SCHEMA_VERSION
        self._check_envelope(topic, enriched, principal)
        if self.payload_validator is not None:
            try:
                self.payload_validator(topic, enriched)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reject malformed record
                self.metrics.schema_violations += 1
                self.metrics.publish_errors += 1
                _LOG.warning(
                    "pantheon_payload_schema_violation",
                    extra={
                        "topic": topic,
                        "principal": principal,
                        "error_type": type(exc).__name__,
                    },
                )
                raise
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
            if topic in MUTATION_TOPICS:
                # Fail toward safety: a mutation record with no resource key
                # would round-robin across partitions, so two concurrent
                # mutations on the same resource could interleave (the
                # per-resource mutex is gone). Refuse the publish rather than
                # emit an unserialized mutation.
                self.metrics.publish_errors += 1
                raise ValueError(
                    f"refusing to publish mutation topic {topic!r} with an empty "
                    "partition key (no resource_id / correlation_id) - per-resource "
                    "ordering cannot be guaranteed"
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
        """Count shared-envelope gaps and reject incomplete owned objects.

        The wire contract (agent-pantheon.md 6.1) says every message carries
        a stripped, bounded ``correlation_id`` and ``idempotency_key``.
        Missing or oversized keys break tracing or at-least-once dedup
        downstream, so every owned object topic fails closed. Mutation
        records keep the extra ``resource_id`` requirement for ordering.
        """
        mutable_payload = payload if isinstance(payload, dict) else dict(payload)
        invalid = list(normalize_owned_object_envelope(topic, mutable_payload))
        if topic in MUTATION_TOPICS and not str(mutable_payload.get("resource_id", "")).strip():
            invalid.append("resource_id")
        if invalid:
            self.metrics.invalid_envelope_fields += len(invalid)
            self.metrics.publish_errors += 1
            if "correlation_id" in invalid:
                self.metrics.missing_correlation_id += 1
            if "idempotency_key" in invalid:
                self.metrics.missing_idempotency_key += 1
            if "resource_id" in invalid:
                self.metrics.missing_resource_id += 1
            fields = ", ".join(invalid)
            raise ValueError(
                f"refusing to publish owned object topic {topic!r}: invalid required "
                f"envelope field(s): {fields}"
            )
        payload = mutable_payload
        missing = missing_mutation_envelope_fields(topic, payload)
        if not str(payload.get("correlation_id", "")).strip():
            self.metrics.missing_correlation_id += 1
            _LOG.warning(
                "pantheon_missing_correlation_id",
                extra={"topic": topic, "principal": principal},
            )
        if topic in MUTATION_TOPICS and not str(payload.get("resource_id", "")).strip():
            self.metrics.missing_resource_id += 1
            _LOG.warning(
                "pantheon_missing_resource_id",
                extra={"topic": topic, "principal": principal},
            )
        if topic in MUTATION_TOPICS and not str(payload.get("idempotency_key", "")).strip():
            self.metrics.missing_idempotency_key += 1
            _LOG.warning(
                "pantheon_missing_idempotency_key",
                extra={"topic": topic, "principal": principal},
            )
        if missing:
            self.metrics.publish_errors += 1
            fields = ", ".join(missing)
            raise ValueError(
                f"refusing to publish mutation topic {topic!r}: missing required "
                f"envelope field(s): {fields}"
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
                consumer_id = f"{agent_name}:{topic}"
                self._consumer_states[consumer_id] = "idle"
                task = asyncio.create_task(
                    self._consume(
                        topic=topic,
                        group_id=group_id,
                        consumer_id=consumer_id,
                        handler=handler,
                    ),
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
        tracked = tuple(self._tasks)
        for task in tracked:
            if not task.done():
                task.cancel()
        pending: set[asyncio.Task[None]] = set(tracked)
        completed: set[asyncio.Task[None]] = set()
        if pending:
            done, pending = await asyncio.wait(pending, timeout=self.shutdown_timeout)
            completed.update(done)
        if pending:
            _LOG.warning(
                "pantheon_bridge_shutdown_finalizing",
                extra={"pending_consumers": len(pending)},
            )
            done, pending = await asyncio.wait(pending, timeout=self.shutdown_timeout)
            completed.update(done)
        if completed:
            await asyncio.gather(*completed, return_exceptions=True)
        self._tasks = [task for task in tracked if task in pending]
        if pending:
            _LOG.error(
                "pantheon_bridge_shutdown_incomplete",
                extra={"pending_consumers": len(pending)},
            )

    async def _consume(
        self,
        *,
        topic: str,
        group_id: str,
        consumer_id: str,
        handler: Handler,
    ) -> None:
        attempt = 0
        while True:
            halted = topic in MUTATION_TOPICS and await is_ordered_halted(
                self.halt_state_store, group_id=group_id, topic=topic
            )
            if halted:
                self._mark_consumer_terminal(consumer_id, "halted")
                return
            stream = self.provider.subscribe(topic, group_id)
            try:
                self._consumer_states[consumer_id] = "connecting"
                self._consumer_states[consumer_id] = "idle"
                async for envelope in stream:
                    self._consumer_states[consumer_id] = "running"
                    try:
                        self._validate_inbound_payload(topic, envelope.payload)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - malformed wire record
                        await self._safe_dead_letter(
                            group_id=group_id,
                            topic=topic,
                            envelope=envelope,
                            reason=f"inbound validation failed: {type(exc).__name__}",
                        )
                        continue
                    try:
                        await notify_handler_observer(
                            self,
                            agent=group_id.rsplit(".", 1)[-1],
                            topic=topic,
                            phase=AgentHandlerPhase.STARTED,
                            payload=envelope.payload,
                        )
                        await self._deliver(topic, handler, envelope.payload)
                        await notify_handler_observer(
                            self,
                            agent=group_id.rsplit(".", 1)[-1],
                            topic=topic,
                            phase=AgentHandlerPhase.COMPLETED,
                            payload=envelope.payload,
                        )
                        self.metrics.delivered += 1
                        self._consumer_delivery_counts[consumer_id] = (
                            self._consumer_delivery_counts.get(consumer_id, 0) + 1
                        )
                        self._consumer_last_delivery_at[consumer_id] = (
                            asyncio.get_running_loop().time()
                        )
                        self._consumer_states[consumer_id] = "idle"
                        attempt = 0  # progress resets the backoff window
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - route to DLQ, keep loop alive
                        await notify_handler_observer(
                            self,
                            agent=group_id.rsplit(".", 1)[-1],
                            topic=topic,
                            phase=AgentHandlerPhase.FAILED,
                            payload=envelope.payload,
                            error_type=type(exc).__name__,
                        )
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
                        dead_letter_failed = False
                        try:
                            await self._safe_dead_letter(
                                group_id=group_id,
                                topic=topic,
                                envelope=envelope,
                                reason=f"handler error: {type(exc).__name__}",
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as dlq_exc:  # noqa: BLE001 - ordered topics must halt
                            dead_letter_failed = True
                            _LOG.error(
                                "pantheon_dead_letter_terminal_failure",
                                extra={
                                    "group_id": group_id,
                                    "topic": topic,
                                    "offset": envelope.offset,
                                    "error_type": type(dlq_exc).__name__,
                                },
                            )
                        if self.halt_ordered_topic_on_poison and topic in MUTATION_TOPICS:
                            self.metrics.ordered_poison_halts += 1
                            await persist_ordered_halt(
                                self.halt_state_store,
                                consumer_id=consumer_id,
                                topic=topic,
                                group_id=group_id,
                                offset=int(envelope.offset or 0),
                                key=envelope.key,
                            )
                            self._mark_consumer_terminal(consumer_id, "halted")
                            _LOG.error(
                                "pantheon_ordered_topic_halted",
                                extra={
                                    "group_id": group_id,
                                    "topic": topic,
                                    "offset": envelope.offset,
                                },
                            )
                            return
                        if dead_letter_failed:
                            raise
                # Iterator ended normally (finite in-memory drain): done.
                self._consumer_states[consumer_id] = "stopped"
                return
            except asyncio.CancelledError:
                self._consumer_states[consumer_id] = "stopped"
                raise
            except Exception:
                self.metrics.consumers_crashed += 1
                attempt += 1
                if attempt > self.max_consumer_restarts:
                    self.metrics.consumers_gave_up += 1
                    self._mark_consumer_terminal(consumer_id, "gave_up")
                    _LOG.exception(
                        "pantheon_consumer_gave_up",
                        extra={
                            "group_id": group_id,
                            "topic": topic,
                            "attempts": attempt,
                        },
                    )
                    return
                self._consumer_states[consumer_id] = "restarting"
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
            finally:
                # Close here so the provider tears the broker connection down
                # inside this task rather than at interpreter finalization.
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    await aclose()

    def _mark_consumer_terminal(self, consumer_id: str, state: str) -> None:
        self._consumer_states[consumer_id] = state
        observer = self.consumer_state_observer
        if observer is None:
            return
        agent, topic = consumer_id.split(":", 1)
        try:
            observer(agent, topic, state)
        except Exception as exc:  # noqa: BLE001 - observer must not break isolation
            _LOG.warning(
                "pantheon_consumer_state_observer_failed",
                extra={
                    "agent": agent,
                    "topic": topic,
                    "state": state,
                    "error_type": type(exc).__name__,
                },
            )

    async def clear_ordered_poison_halt(self, *, topic: str, agent_name: str) -> bool:
        if self.halt_state_store is None:
            return False
        group_id = f"{self.consumer_group_prefix}.{agent_name}"
        cleared = await clear_ordered_halt(self.halt_state_store, group_id=group_id, topic=topic)
        consumer_id = f"{agent_name}:{topic}"
        if cleared and self._consumer_states.get(consumer_id) == "halted":
            self._consumer_states[consumer_id] = "cleared"
        return cleared

    def _producer_authorized(self, topic: str, payload: Payload) -> bool:
        """Consumer-side single-writer check.

        Returns ``True`` when the record may be delivered. A topic with no
        declared owner (the raw ingress topic, or an alternate stream) is
        not a pantheon object topic, so there is nothing to verify against -
        allow it. An owned topic requires its declared principal; a missing or
        mismatched ``producer_principal`` is rejected and counted.
        """
        owner = self.registry.owner_of_topic(topic)
        if owner is None:
            return True
        principal = str(payload.get("producer_principal", ""))
        if principal != owner:
            self.metrics.producer_principal_mismatch += 1
            _LOG.warning(
                "pantheon_producer_principal_mismatch",
                extra={"topic": topic, "principal": principal or "<missing>", "owner": owner},
            )
            return False
        return True

    def _validate_inbound_payload(self, topic: str, payload: Payload) -> None:
        """Apply the publish/redrive validation boundary before live delivery."""

        if not self._producer_authorized(topic, payload):
            raise ValueError(
                "producer_principal "
                f"{payload.get('producer_principal')!r} is not the owner of {topic!r}"
            )
        self._check_envelope(topic, payload, str(payload.get("producer_principal", "")))
        if self.payload_validator is not None:
            self.payload_validator(topic, payload)

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
                timeout = self.handler_timeouts.get(topic, self.handler_timeout)
                if timeout is not None:
                    # A handler that never returns (a stuck backend call, a
                    # deadlock) would wedge the whole consumer - alive but
                    # delivering nothing. Bound it: a timeout is treated as a
                    # handler failure (retry / DLQ), keeping the subscription
                    # making progress.
                    await asyncio.wait_for(handler(topic, dict(payload)), timeout)
                else:
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

    async def _notify_handler_observer(
        self,
        *,
        agent: str,
        topic: str,
        phase: AgentHandlerPhase,
        payload: Payload,
        error_type: str | None = None,
    ) -> None:
        await notify_handler_observer(
            self,
            agent=agent,
            topic=topic,
            phase=phase,
            payload=payload,
            error_type=error_type,
        )

    async def _safe_dead_letter(
        self,
        *,
        group_id: str,
        topic: str,
        envelope: Any,
        reason: str,
    ) -> None:
        """Route a poison record to the DLQ with bounded retry.

        A persistent DLQ failure propagates so the owning consumer restarts
        without silently advancing beyond a record that was never parked.
        """
        await self._dead_letter_payload(
            group_id=group_id,
            topic=topic,
            key=envelope.key,
            payload=envelope.payload,
            reason=reason,
        )

    async def _dead_letter_payload(
        self,
        *,
        group_id: str,
        topic: str,
        key: str,
        payload: Payload,
        reason: str,
    ) -> None:
        for attempt in range(self.dead_letter_max_retries + 1):
            try:
                dead_letter = self.provider.dead_letter(topic, key, payload, reason=reason)
                if self.dead_letter_timeout is None:
                    await dead_letter
                else:
                    await asyncio.wait_for(dead_letter, self.dead_letter_timeout)
                self.metrics.dead_lettered += 1
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.dead_letter_errors += 1
                if attempt >= self.dead_letter_max_retries:
                    _LOG.exception(
                        "pantheon_dead_letter_failed",
                        extra={"group_id": group_id, "topic": topic, "attempt": attempt + 1},
                    )
                    raise
                await asyncio.sleep(self.dead_letter_retry_backoff * (2**attempt))

    async def redrive(
        self,
        topic: str,
        handler: Handler,
        *,
        group_id: str | None = None,
        max_records: int | None = None,
    ) -> dict[str, int]:
        """Reprocess dead-lettered records for ``topic`` (operator tool).

        The DLQ is write-only on the hot path - a poison record parks in
        ``<topic>.dlq`` and stays there. This is the deliberate,
        operator-driven redrive: after the root cause is fixed, it reads
        ``<topic>.dlq`` under a fresh consumer group, unwraps each record to
        its original payload, and re-delivers it to ``handler``. A record
        that fails again is re-dead-lettered (never lost). Returns
        ``{"redriven": n, "failed": m}``.

        This is NOT part of the perpetual consumer loop - it is invoked
        explicitly (a CLI / admin action) so a redrive is always a
        conscious decision, never automatic.
        """
        if max_records is not None and max_records <= 0:
            raise ValueError("max_records MUST be greater than zero when provided")
        dlq_topic = f"{topic}.dlq"
        gid = group_id or f"{self.consumer_group_prefix}.redrive.{topic}"
        redriven = 0
        failed = 0
        dlq_stream = self.provider.subscribe(dlq_topic, gid)
        try:
            async for envelope in dlq_stream:
                wrapped = dict(envelope.payload)
                # dead_letter wraps the record as {original_topic, reason,
                # payload}; unwrap to the original payload for re-delivery.
                original = wrapped.get("payload", wrapped)
                payload = dict(original) if isinstance(original, Mapping) else {}
                try:
                    if not self._producer_authorized(topic, payload):
                        raise ValueError("redrive payload has an unauthorized producer principal")
                    self._check_envelope(topic, payload, str(payload.get("producer_principal", "")))
                    if self.payload_validator is not None:
                        self.payload_validator(topic, payload)
                    await self._deliver(topic, handler, payload)
                    redriven += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - re-park a still-failing record
                    failed += 1
                    await self._dead_letter_payload(
                        group_id=gid,
                        topic=topic,
                        key=envelope.key,
                        payload=payload,
                        reason=f"redrive failed: {type(exc).__name__}",
                    )
                if max_records is not None and (redriven + failed) >= max_records:
                    break
        finally:
            aclose = getattr(dlq_stream, "aclose", None)
            if aclose is not None:
                await aclose()
        _LOG.info(
            "pantheon_redrive_complete",
            extra={"topic": topic, "redriven": redriven, "failed": failed},
        )
        return {"redriven": redriven, "failed": failed}


__all__ = ["AgentHandlerObserver", "AgentHandlerPhase", "BridgeMetrics", "EventBusBridge"]
