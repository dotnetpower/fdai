"""Bridge pantheon dispatch to the async ``EventBus`` provider Protocol."""

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
    is_ordered_halted,
    persist_ordered_halt,
)
from fdai.agents._framework.bus_poison_resume import (
    clear_ordered_poison_halt,
    consumer_id_for_group,
    resume_ordered_consumer,
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
from fdai.shared.providers.event_bus import EventBus, EventPublishNotAttemptedError, PublishReceipt
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)

Payload = Mapping[str, object]
Handler = Callable[[str, dict[str, object]], Awaitable[None]]
PayloadValidator = Callable[[str, Mapping[str, object]], None]
ConsumerStateObserver = Callable[[str, str, str], None]
DEFAULT_REDRIVE_BATCH_SIZE = 100
"""Optional publish-side contract check (topic, payload) -> None; raises on
an invalid payload. Wire a ContractValidator-backed callable here to reject
a malformed record at the publish boundary (fail closed)."""


def _assert_known_topic(topic: str, agent_name: str) -> None:
    if topic.startswith("object.") and topic not in OWNED_OBJECT_TOPICS:
        _LOG.error(
            "pantheon_subscribe_unknown_topic",
            extra={"topic": topic, "agent": agent_name},
        )
        raise ValueError(f"unknown pantheon object topic {topic!r} for agent {agent_name!r}")


@dataclass
class EventBusBridge:
    """Adapter that lets pantheon agents talk to a real ``EventBus``."""

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
    redrive_batch_size: int = DEFAULT_REDRIVE_BATCH_SIZE
    _subs: dict[str, list[tuple[str, Handler]]] = field(default_factory=lambda: defaultdict(list))
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _consumer_states: dict[str, str] = field(default_factory=dict)
    _consumer_delivery_counts: dict[str, int] = field(default_factory=dict)
    _consumer_last_delivery_at: dict[str, float] = field(default_factory=dict)
    _handler_observer_failures: dict[tuple[str, str, AgentHandlerPhase], int] = field(
        default_factory=dict
    )
    _halted_ordered_topics: set[str] = field(default_factory=set)
    _validation_dlq_keys: set[tuple[str, int | None, str]] = field(default_factory=set)
    _intentional_stop: bool = False
    metrics: BridgeMetrics = field(default_factory=BridgeMetrics)

    # ---- pantheon-style API --------------------------------------------

    def subscribe(self, topic: str, agent_name: str, handler: Handler) -> None:
        _assert_known_topic(topic, agent_name)
        existing = self._subs[topic]
        if any(name == agent_name and h == handler for name, h in existing):
            _LOG.warning(
                "pantheon_duplicate_subscription",
                extra={"topic": topic, "agent": agent_name},
            )
            return
        existing.append((agent_name, handler))

    def snapshot(self) -> dict[str, object]:
        live = sum(1 for t in self._tasks if not t.done())
        unavailable_states = {"gave_up", "halted"}
        unavailable_agents = sorted(
            {
                consumer_id.split(":", 1)[0]
                for consumer_id, state in self._consumer_states.items()
                if state in unavailable_states
            }
            | set(self.metrics.degraded_handler_agents())
        )
        degraded_consumers = {
            consumer_id: state
            for consumer_id, state in sorted(self._consumer_states.items())
            if state in unavailable_states | {"restarting"}
        }
        health_failures = self.metrics.health_failures()
        stopped = self._intentional_stop
        status = (
            "degraded"
            if unavailable_agents or health_failures
            else "stopped"
            if stopped
            else "healthy"
        )
        return {
            "subscriptions": sum(len(v) for v in self._subs.values()),
            "consumers_live": live,
            "consumer_states": dict(sorted(self._consumer_states.items())),
            "degraded_consumer_states": degraded_consumers,
            "consumer_deliveries": dict(sorted(self._consumer_delivery_counts.items())),
            "consumer_last_delivery_at": dict(sorted(self._consumer_last_delivery_at.items())),
            "unavailable_agents": unavailable_agents,
            "status": status,
            "health_failures": list(health_failures),
            "health_window": {"scope": "process", "threshold": 1},
            "metrics": self.metrics.as_dict(),
            "recent_rejected_edges": list(self.metrics.recent_rejections()),
        }

    async def publish(self, principal: str, topic: str, payload: Payload) -> PublishReceipt:
        self.registry.assert_can_publish(principal, topic)
        enriched = dict(payload)
        enriched["producer_principal"] = principal
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
                self.metrics.record_rejection(
                    topic=topic,
                    principal=principal,
                    reason=f"publish schema violation: {type(exc).__name__}",
                    payload=enriched,
                )
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
            self.metrics.empty_partition_keys += 1
            _LOG.warning(
                "pantheon_empty_partition_key",
                extra={"topic": topic, "principal": principal},
            )
            if topic in MUTATION_TOPICS:
                self.metrics.publish_errors += 1
                self.metrics.record_rejection(
                    topic=topic,
                    principal=principal,
                    reason="empty mutation partition key",
                    payload=enriched,
                )
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
            self.metrics.record_rejection(
                topic=topic,
                principal=principal,
                reason="invalid envelope fields: " + ",".join(invalid),
                payload=mutable_payload,
            )
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
            self.metrics.record_rejection(
                topic=topic,
                principal=principal,
                reason="missing mutation fields: " + ",".join(missing),
                payload=payload if isinstance(payload, dict) else dict(payload),
            )
            fields = ", ".join(missing)
            raise ValueError(
                f"refusing to publish mutation topic {topic!r}: missing required "
                f"envelope field(s): {fields}"
            )

    # ---- consumer loop -------------------------------------------------

    async def run(self) -> None:
        if self._tasks:
            raise RuntimeError("EventBusBridge.run() is already running; call stop() first")
        self._intentional_stop = False
        for topic, subs in self._subs.items():
            agent_topic_counts: dict[str, int] = defaultdict(int)
            agent_topic_totals: dict[str, int] = defaultdict(int)
            for agent_name, _handler in subs:
                agent_topic_totals[agent_name] += 1
            for agent_name, handler in subs:
                agent_topic_counts[agent_name] += 1
                ordinal = agent_topic_counts[agent_name]
                total = agent_topic_totals[agent_name]
                group_id = self._consumer_group_id(agent_name, topic, ordinal, total)
                consumer_id = self._consumer_id(agent_name, topic, ordinal, total)
                self._consumer_states[consumer_id] = "idle"
                task = asyncio.create_task(
                    self._consume(
                        agent_name=agent_name,
                        topic=topic,
                        group_id=group_id,
                        consumer_id=consumer_id,
                        handler=handler,
                    ),
                    name=f"pantheon-consumer.{consumer_id}",
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
                    _LOG.error(
                        "pantheon_bridge_consumer_crashed",
                        extra={
                            "task_name": task.get_name(),
                            "error_type": type(result).__name__,
                            "failure_code": "consumer_crashed",
                        },
                    )
            if crashed:
                _LOG.error(
                    "pantheon_bridge_consumers_crashed",
                    extra={"crashed": crashed, "total": len(results)},
                )
        finally:
            await self.stop()

    async def stop(self) -> None:
        self._intentional_stop = True
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
        agent_name: str,
        topic: str,
        group_id: str,
        consumer_id: str,
        handler: Handler,
    ) -> None:
        attempt = 0
        while True:
            halted = topic in self._halted_ordered_topics or (
                topic in MUTATION_TOPICS
                and await is_ordered_halted(self.halt_state_store, group_id=group_id, topic=topic)
            )
            if halted:
                self._mark_consumer_terminal(consumer_id, "halted")
                return
            stream = self.provider.subscribe(topic, group_id)
            try:
                self._consumer_states[consumer_id] = "connecting"
                self._consumer_states[consumer_id] = "idle"
                async for envelope in stream:
                    if topic in self._halted_ordered_topics:
                        self._mark_consumer_terminal(consumer_id, "halted")
                        return
                    self._consumer_states[consumer_id] = "running"
                    try:
                        self._validate_inbound_payload(topic, envelope.payload)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - malformed wire record
                        self.metrics.record_rejection(
                            topic=topic,
                            group_id=group_id,
                            reason=f"inbound validation failed: {type(exc).__name__}",
                            payload=dict(envelope.payload),
                            offset=envelope.offset,
                        )
                        await self._safe_dead_letter(
                            agent_name=agent_name,
                            group_id=group_id,
                            topic=topic,
                            envelope=envelope,
                            reason=f"inbound validation failed: {type(exc).__name__}",
                            validation_dedupe=True,
                        )
                        continue
                    try:
                        await notify_handler_observer(
                            self,
                            agent=agent_name,
                            topic=topic,
                            phase=AgentHandlerPhase.STARTED,
                            payload=envelope.payload,
                        )
                        await self._deliver(topic, handler, envelope.payload)
                        await notify_handler_observer(
                            self,
                            agent=agent_name,
                            topic=topic,
                            phase=AgentHandlerPhase.COMPLETED,
                            payload=envelope.payload,
                        )
                        self.metrics.delivered += 1
                        self.metrics.record_handler_result(agent_name, failed=False)
                        self._consumer_delivery_counts[consumer_id] = (
                            self._consumer_delivery_counts.get(consumer_id, 0) + 1
                        )
                        self._consumer_last_delivery_at[consumer_id] = (
                            asyncio.get_running_loop().time()
                        )
                        self._consumer_states[consumer_id] = "idle"
                        attempt = 0
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - route to DLQ, keep loop alive
                        if isinstance(exc, EventPublishNotAttemptedError):
                            raise
                        await notify_handler_observer(
                            self,
                            agent=agent_name,
                            topic=topic,
                            phase=AgentHandlerPhase.FAILED,
                            payload=envelope.payload,
                            error_type=type(exc).__name__,
                        )
                        self.metrics.handler_errors += 1
                        self.metrics.record_handler_result(agent_name, failed=True)
                        _LOG.warning(
                            "pantheon_handler_error",
                            extra={
                                "group_id": group_id,
                                "topic": topic,
                                "offset": envelope.offset,
                                "error_type": type(exc).__name__,
                                "failure_code": "handler_error",
                            },
                        )
                        dead_letter_failed = False
                        try:
                            await self._safe_dead_letter(
                                agent_name=agent_name,
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
                            self._halted_ordered_topics.add(topic)
                            await persist_ordered_halt(
                                self.halt_state_store,
                                consumer_id=consumer_id,
                                topic=topic,
                                group_id=group_id,
                                offset=int(envelope.offset or 0),
                                key=envelope.key,
                            )
                            self._mark_consumer_terminal(consumer_id, "halted")
                            self._mark_topic_consumers_terminal(topic, "halted")
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
            finally:
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
        return await clear_ordered_poison_halt(self, topic=topic, agent_name=agent_name)

    def resume_ordered_consumer_after_clear(
        self,
        *,
        topic: str,
        agent_name: str,
        group_id: str | None = None,
    ) -> bool:
        consumer_id = consumer_id_for_group(
            self, agent_name=agent_name, topic=topic, group_id=group_id
        )
        if self._consumer_states.get(consumer_id) not in {"halted", "cleared"}:
            return False
        self._consumer_states[consumer_id] = "cleared"
        return resume_ordered_consumer(self, topic=topic, agent_name=agent_name, group_id=group_id)

    def _producer_authorized(self, topic: str, payload: Payload) -> bool:
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
        if not self._producer_authorized(topic, payload):
            raise ValueError(
                "producer_principal "
                f"{payload.get('producer_principal')!r} is not the owner of {topic!r}"
            )
        self._check_envelope(topic, payload, str(payload.get("producer_principal", "")))
        if self.payload_validator is not None:
            self.payload_validator(topic, payload)

    async def _deliver(self, topic: str, handler: Handler, payload: Payload) -> None:
        last_exc: Exception
        for attempt in range(self.handler_max_retries + 1):
            try:
                timeout = self.handler_timeouts.get(topic, self.handler_timeout)
                if timeout is not None:
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

    def _consumer_group_id(self, agent: str, topic: str, ordinal: int, total: int) -> str:
        if total == 1:
            return f"{self.consumer_group_prefix}.{agent}"
        safe_topic = topic.replace(".", "-")
        return f"{self.consumer_group_prefix}.{agent}.{safe_topic}.{ordinal}"

    def _consumer_id(self, agent: str, topic: str, ordinal: int, total: int) -> str:
        return f"{agent}:{topic}" if total == 1 else f"{agent}:{topic}#{ordinal}"

    def _mark_topic_consumers_terminal(self, topic: str, state: str) -> None:
        marker = f":{topic}"
        for consumer_id in tuple(self._consumer_states):
            if marker in consumer_id:
                self._mark_consumer_terminal(consumer_id, state)

    async def _safe_dead_letter(
        self,
        *,
        agent_name: str | None = None,
        group_id: str,
        topic: str,
        envelope: Any,
        reason: str,
        validation_dedupe: bool = False,
    ) -> None:
        dedupe_key = (topic, envelope.offset, envelope.key)
        if validation_dedupe and dedupe_key in self._validation_dlq_keys:
            return
        resolved_agent_name = agent_name or group_id.rsplit(".", 1)[-1]
        await self._dead_letter_payload(
            agent_name=resolved_agent_name,
            group_id=group_id,
            topic=topic,
            key=envelope.key,
            payload=envelope.payload,
            reason=reason,
            offset=envelope.offset,
        )
        if validation_dedupe:
            self._validation_dlq_keys.add(dedupe_key)

    async def _dead_letter_payload(
        self,
        *,
        agent_name: str,
        group_id: str,
        topic: str,
        key: str,
        payload: Payload,
        reason: str,
        offset: int | None = None,
    ) -> None:
        dlq_payload = dict(payload)
        dlq_payload["__fdai_dlq_metadata__"] = {
            "consumer_group": group_id,
            "agent": agent_name,
            "topic": topic,
            "offset": offset,
        }
        for attempt in range(self.dead_letter_max_retries + 1):
            try:
                dead_letter = self.provider.dead_letter(topic, key, dlq_payload, reason=reason)
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
        if max_records is not None and max_records <= 0:
            raise ValueError("max_records MUST be greater than zero when provided")
        limit = max_records if max_records is not None else self.redrive_batch_size
        if limit <= 0:
            raise ValueError("redrive_batch_size MUST be greater than zero")
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
                        agent_name=gid.rsplit(".", 1)[-1],
                        group_id=gid,
                        topic=topic,
                        key=envelope.key,
                        payload=payload,
                        reason=f"redrive failed: {type(exc).__name__}",
                        offset=envelope.offset,
                    )
                if (redriven + failed) >= limit:
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


__all__ = [
    "AgentHandlerObserver",
    "AgentHandlerPhase",
    "BridgeMetrics",
    "DEFAULT_REDRIVE_BATCH_SIZE",
    "EventBusBridge",
]
