"""Event-bus consumers and control-loop outcome normalization."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_CONSUMER_GROUP,
    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
    decode_notification_delivery_receipt,
)
from fdai_service_contracts.schema import (
    ContractValidator,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

from fdai.agents import ShadowDivergenceLedger
from fdai.composition.readiness import OperationalReadinessEventHandler
from fdai.core.control_loop import ControlLoop, ControlLoopOutcome, ControlLoopResult
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.delivery.notifications import NotificationDeliveryReceiptApplier
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.hil_registry import HilWorkflowDecisionRegistry

_LOGGER = logging.getLogger("fdai.startup")
_LOOP_LOGGER = logging.getLogger("fdai.control_loop")


async def _consume_operational_readiness(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    handler: OperationalReadinessEventHandler,
    stop: asyncio.Event,
) -> None:
    """Consume typed ownership transfers through the Forseti-owned review workflow."""

    async with subscription(bus, topic, group_id) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            try:
                report = await handler.handle(envelope.payload)
            except Exception as exc:  # noqa: BLE001 - broker boundary isolation
                reason = f"operational_readiness_consume_error:{type(exc).__name__}"
                _LOOP_LOGGER.exception(
                    "operational_readiness_consume_error",
                    extra={"key": envelope.key, "offset": envelope.offset},
                )
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    reason,
                )
                continue
            if report is not None:
                _LOOP_LOGGER.info(
                    "operational_readiness_reviewed",
                    extra={
                        "key": envelope.key,
                        "offset": envelope.offset,
                        "verdict": report.verdict.value,
                        "blocks_handoff": report.blocks_handoff,
                    },
                )


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

    async with subscription(bus, raw_topic, "fdai-huginn-resource-discovery") as stream:
        async for envelope in stream:
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
    async with subscription(bus, topic, group_id) as stream:
        async for envelope in stream:
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


async def _consume_notification_receipts(
    *,
    bus: EventBus,
    topic: str,
    applier: NotificationDeliveryReceiptApplier,
    stop: asyncio.Event,
    validator: ContractValidator | None = None,
) -> None:
    """Apply authenticated publication observations to durable delivery state.

    The Operator Service already verified the provider signature, freshness, and
    bounded body before publishing. This consumer still validates the envelope
    against ``notification-delivery-receipt`` because a broker payload is
    untrusted input, and it dead-letters anything that does not match an
    accepted delivery instead of rewriting a prior routing decision.
    """
    contract = validator or JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    async with subscription(bus, topic, NOTIFICATION_DELIVERY_RECEIPT_CONSUMER_GROUP) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            try:
                contract.validate(
                    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
                    envelope.payload,
                    version=NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
                )
                receipt = decode_notification_delivery_receipt(envelope.payload)
                record = await applier.apply(receipt)
            except Exception as exc:  # noqa: BLE001 - broker boundary isolation
                reason = f"notification_receipt_consume_error:{type(exc).__name__}"
                _LOOP_LOGGER.warning(
                    "notification_receipt_consume_error",
                    extra={"key": envelope.key, "offset": envelope.offset, "reason": reason},
                )
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    reason,
                )
                continue
            _LOOP_LOGGER.info(
                "notification_delivery_observed",
                extra={
                    "channel_id": record.channel_id,
                    "delivery_state": record.state.value,
                    "publication_result": receipt.publication_result,
                },
            )


async def _consume_hil_decisions(
    *,
    bus: EventBus,
    topic: str,
    coordinator: HilResumeCoordinator,
    stop: asyncio.Event,
    workflow_registry: HilWorkflowDecisionRegistry | None = None,
) -> None:
    """Route one durable human decision to its authoritative owner.

    A ``workflow`` park is one quorum slot owned by the workflow approval
    registry: resolving it through :meth:`HilResumeCoordinator.resolve` would
    bypass quorum accounting, duplicate-approver refusal, and self-approval
    refusal, and would mark a slot park terminal without a claim. Only an
    ``action`` park resumes through the coordinator, which is the sole path
    that can reach an executor.
    """
    from fdai.shared.providers.hil_channel import HilDecision
    from fdai.shared.providers.hil_registry import HilApprovalDecision

    async with subscription(bus, topic, "fdai-hil-resume") as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            payload = envelope.payload
            try:
                approval_id = str(payload["approval_id"])
                decision = HilDecision(str(payload["decision"]))
                approver_oid = str(payload["approver_oid"])
                justification = str(payload.get("justification") or "")
                if not approval_id or not approver_oid:
                    raise ValueError("approval_id and approver_oid MUST be non-empty")
                route = (
                    await workflow_registry.get_decision_route(approval_id)
                    if workflow_registry is not None
                    else "action"
                )
                if route == "workflow":
                    if workflow_registry is None:  # pragma: no cover - route implies binding
                        raise ValueError("workflow decision route has no bound registry")
                    await _record_workflow_decision(
                        registry=workflow_registry,
                        approval_id=approval_id,
                        decision=HilApprovalDecision(decision.value),
                        approver_oid=approver_oid,
                        justification=justification,
                        payload=payload,
                    )
                    continue
                await coordinator.resolve(
                    approval_id=approval_id,
                    decision=decision,
                    approver_oid=approver_oid,
                    reason=justification,
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


async def _record_workflow_decision(
    *,
    registry: HilWorkflowDecisionRegistry,
    approval_id: str,
    decision: Any,
    approver_oid: str,
    justification: str,
    payload: Mapping[str, Any],
) -> None:
    """Fill exactly one quorum slot through the authoritative registry."""
    idempotency_key = str(payload.get("idempotency_key") or "")
    if not idempotency_key:
        pending = await registry.get_pending_by_approval_id(approval_id)
        if pending is None:
            raise ValueError("workflow approval slot is not pending and carries no key")
        idempotency_key = pending.idempotency_key
    decided_at = _decided_at(payload.get("decided_at"))
    await registry.record_decision(
        idempotency_key=idempotency_key,
        decision=decision,
        approver_oid=approver_oid,
        justification=justification,
        decided_at=decided_at,
    )


def _decided_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("HIL decision decided_at is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("HIL decision decided_at MUST carry a timezone")
    return parsed


async def _consume_canaries(
    *,
    bus: EventBus,
    topic: str,
    control_loop: ControlLoop,
    stop: asyncio.Event,
) -> None:
    """Consume the separately authorized canary topic without IRP or learning hooks."""
    async with subscription(bus, topic, "fdai-canary") as stream:
        async for envelope in stream:
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


def _log_pantheon_exit(task: asyncio.Task[None], *, stop: asyncio.Event | None = None) -> None:
    """Done-callback for the isolated pantheon task.

    A pantheon crash or early exit is surfaced here without touching the
    P1 wait set, so the shadow overlay can never take the primary control
    plane down with it. The readiness supervisor returns normally once
    ``stop`` is set, so a signalled shutdown is a clean exit, not an early one.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOGGER.error("pantheon_runtime_failed", exc_info=exc)
    elif stop is None or not stop.is_set():
        _LOGGER.warning("pantheon_runtime_exited_early")
