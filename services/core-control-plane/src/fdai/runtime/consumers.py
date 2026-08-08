"""Event-bus consumers and control-loop outcome normalization."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fdai.agents import ShadowDivergenceLedger
from fdai.core.control_loop import ControlLoop, ControlLoopOutcome, ControlLoopResult
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger("fdai.startup")
_LOOP_LOGGER = logging.getLogger("fdai.control_loop")


async def _consume_resource_changes(
    *,
    bus: EventBus,
    raw_topic: str,
    canonical_topic: str,
    resource_types: ResourceTypeRegistry,
    stop: asyncio.Event,
) -> None:
    """Normalize Event Grid resource changes into the canonical Huginn ingress."""

    from fdai.delivery.azure.resource_change import normalize_resource_change_events

    async for envelope in bus.subscribe(raw_topic, "fdai-huginn-resource-discovery"):
        if stop.is_set():
            return
        try:
            events = normalize_resource_change_events(
                envelope.payload,
                resource_types=resource_types,
            )
        except Exception as exc:  # noqa: BLE001 - broker boundary isolation
            reason = f"resource_discovery_normalize_error:{type(exc).__name__}"
            _LOOP_LOGGER.exception(
                "resource_discovery_normalize_error",
                extra={"key": envelope.key, "offset": envelope.offset},
            )
            await bus.dead_letter(
                envelope.topic,
                envelope.key,
                envelope.payload,
                reason,
            )
            continue
        for event in events:
            await bus.publish(
                canonical_topic,
                event.resource_ref or str(event.event_id),
                event.model_dump(mode="json"),
            )


async def _consume(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    control_loop: ControlLoop,
    stop: asyncio.Event,
    divergence: ShadowDivergenceLedger | None = None,
    irp_handler: Any | None = None,
) -> None:
    """Feed every Kafka envelope through the P1 control loop.

    :meth:`ControlLoop.process` is idempotent on ``idempotency_key`` and
    never raises for business errors, so a bad event still writes an
    audit entry and the consumer keeps committing offsets to avoid
    poison-message deadlocks.

    When a ``divergence`` ledger is wired, the authoritative P1 decision
    is recorded against the event's correlation id so it can be joined
    with the pantheon's shadow verdict (shadow-before-enforce baseline).
    """
    async for envelope in bus.subscribe(topic, group_id):
        if stop.is_set():
            return
        _LOOP_LOGGER.info(
            "event_received",
            extra={"topic": envelope.topic, "offset": envelope.offset, "key": envelope.key},
        )
        try:
            result = await control_loop.process(envelope.payload)
        except Exception as exc:  # noqa: BLE001 - process boundary isolation
            reason = f"control_loop_unhandled_error:{type(exc).__name__}"
            _LOOP_LOGGER.exception(
                "control_loop_unhandled_error",
                extra={"key": envelope.key, "offset": envelope.offset},
            )
            # Commit only after both the terminal audit and DLQ write
            # succeed. If either isolation step fails, propagate so the
            # async iterator closes before its post-yield commit and the
            # broker redelivers the event.
            await control_loop.record_unhandled_failure(
                payload=envelope.payload,
                reason=reason,
            )
            await bus.dead_letter(
                envelope.topic,
                envelope.key,
                envelope.payload,
                reason,
            )
            continue
        if divergence is not None:
            payload = envelope.payload
            correlation_id = str(
                payload.get("correlation_id")
                or payload.get("event_id")
                or payload.get("id")
                or envelope.key
            )
            divergence.record_authoritative(correlation_id, _authoritative_decision(result))
        if irp_handler is not None and result.outcome is not ControlLoopOutcome.DEDUPED:
            try:
                await irp_handler.handle(envelope.payload)
            except Exception as exc:  # noqa: BLE001 - isolate the alert-response boundary
                reason = f"irp_event_handler_error:{type(exc).__name__}"
                _LOOP_LOGGER.exception(
                    "irp_event_handler_error",
                    extra={"key": envelope.key, "offset": envelope.offset},
                )
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    reason,
                )
                continue
        _LOOP_LOGGER.info(
            "event_processed",
            extra={
                "outcome": result.outcome.value,
                "tier": result.tier,
                "decision": result.decision,
                "resource_type": result.resource_type,
                "citing_rule_ids": list(result.citing_rule_ids),
            },
        )


async def _consume_hil_decisions(
    *,
    bus: EventBus,
    topic: str,
    coordinator: HilResumeCoordinator,
    stop: asyncio.Event,
) -> None:
    from fdai.shared.providers.hil_channel import HilDecision

    async for envelope in bus.subscribe(topic, "fdai-hil-resume"):
        if stop.is_set():
            return
        payload = envelope.payload
        try:
            approval_id = str(payload["approval_id"])
            decision = HilDecision(str(payload["decision"]))
            approver_oid = str(payload["approver_oid"])
            if not approval_id or not approver_oid:
                raise ValueError("approval_id and approver_oid MUST be non-empty")
            await coordinator.resolve(
                approval_id=approval_id,
                decision=decision,
                approver_oid=approver_oid,
                reason=str(payload.get("justification") or ""),
            )
        except Exception as exc:  # noqa: BLE001 - broker boundary isolation
            reason = f"hil_decision_consume_error:{type(exc).__name__}"
            await bus.dead_letter(
                envelope.topic,
                envelope.key,
                envelope.payload,
                reason,
            )
            continue


async def _consume_canaries(
    *,
    bus: EventBus,
    topic: str,
    control_loop: ControlLoop,
    stop: asyncio.Event,
) -> None:
    """Consume the separately authorized canary topic without IRP or learning hooks."""
    async for envelope in bus.subscribe(topic, "fdai-canary"):
        if stop.is_set():
            return
        try:
            result = await control_loop.process_canary(envelope.payload)
        except Exception as exc:  # noqa: BLE001 - broker boundary isolation
            reason = f"canary_consume_error:{type(exc).__name__}"
            await control_loop.record_unhandled_failure(
                payload=envelope.payload,
                reason=reason,
            )
            await bus.dead_letter(
                envelope.topic,
                envelope.key,
                envelope.payload,
                reason,
            )
            continue
        _LOOP_LOGGER.info(
            "canary_processed",
            extra={
                "outcome": result.outcome.value,
                "event_id": result.event_id,
                "topic": envelope.topic,
            },
        )


def _authoritative_decision(result: ControlLoopResult) -> str:
    """Normalize a P1 :class:`ControlLoopResult` to the shared decision
    vocabulary used by the pantheon (``auto`` / ``hil`` / ``deny`` /
    ``dedupe`` / ``abstain``) so the two sides are directly comparable."""
    outcome = result.outcome
    if outcome == ControlLoopOutcome.EXECUTED:
        return "auto"
    if outcome == ControlLoopOutcome.HIL:
        return "hil"
    if outcome == ControlLoopOutcome.DENIED:
        return "deny"
    if outcome == ControlLoopOutcome.DEDUPED:
        return "dedupe"
    return "abstain"


def _log_pantheon_exit(task: asyncio.Task[None]) -> None:
    """Done-callback for the isolated pantheon task.

    A pantheon crash or early exit is surfaced here without touching the
    P1 wait set, so the shadow overlay can never take the primary control
    plane down with it.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOGGER.error("pantheon_runtime_failed", exc_info=exc)
    else:
        _LOGGER.warning("pantheon_runtime_exited_early")
