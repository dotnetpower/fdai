"""Consume confirmed Operator requests into the Core-owned Incident registry."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

from fdai.agents import OperatorRequestReceiptGate, ReservedOperatorRequestReceipt
from fdai.core.incident import IncidentLifecycleWorkflow, IncidentWorkflowForbiddenError
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai_service_contracts.incident_creation import (
    IncidentCreationRequest,
    incident_creation_receipt_event,
)
from fdai_service_contracts.operator import OperatorRole
from pydantic import ValidationError

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _IncidentPrincipal:
    id: str
    role: str


@dataclass(frozen=True, slots=True)
class IncidentCreationConsumerBinding:
    """Bind one creation-request topic to the Core Incident lifecycle."""

    request_topic: str
    group_id: str
    workflow: IncidentLifecycleWorkflow
    receipt_gate: OperatorRequestReceiptGate | None = None

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume requests until the shared Core stop event is set."""

        await consume_incident_creations(
            bus=bus,
            topic=self.request_topic,
            group_id=self.group_id,
            workflow=self.workflow,
            receipt_gate=self.receipt_gate,
            stop=stop,
        )


async def consume_incident_creations(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    workflow: IncidentLifecycleWorkflow,
    receipt_gate: OperatorRequestReceiptGate | None = None,
    stop: asyncio.Event,
) -> None:
    """Apply valid confirmed requests before advancing at-least-once delivery."""

    async with subscription(bus, topic, group_id) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            try:
                request = IncidentCreationRequest.model_validate(envelope.payload)
                if receipt_gate is None:
                    raise _IncidentCreationReceiptRejectedError(
                        "incident_creation_receipt_gate_unconfigured"
                    )
                if envelope.key != request.target_ref:
                    raise ValueError("incident creation partition key mismatch")
                reserved = await _reserve_receipt(receipt_gate, request)
                if reserved is None:
                    continue
                role = _highest_ordinary_role(request.principal_roles)
                try:
                    await workflow.open_confirmed_operator(
                        principal=_IncidentPrincipal(id=request.principal_id, role=role.value),
                        correlation_keys=(
                            f"resource:{request.arguments.target}",
                            f"operator-request:{request.source_request_id}",
                        ),
                        severity=IncidentSeverity(request.arguments.severity),
                        member_event_ids=(UUID(request.source_request_id),),
                        now=request.confirmed_at,
                    )
                except Exception:
                    await receipt_gate.release(reserved)
                    raise
                try:
                    await receipt_gate.finalize(reserved)
                except ValueError as exc:
                    _LOG.warning(
                        "incident_creation_applied_but_receipt_fence_unfinalized",
                        extra={
                            "source_request_id": request.source_request_id,
                            "target_ref": request.target_ref,
                            "reason": _receipt_rejection_reason(str(exc) or type(exc).__name__),
                        },
                    )
            except _IncidentCreationReceiptRejectedError as exc:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    exc.reason,
                )
            except (IncidentWorkflowForbiddenError, ValidationError, ValueError):
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "incident_creation_request_rejected",
                )


def _highest_ordinary_role(roles: tuple[OperatorRole, ...]) -> OperatorRole:
    rank = {
        OperatorRole.READER: 0,
        OperatorRole.CONTRIBUTOR: 1,
        OperatorRole.APPROVER: 2,
        OperatorRole.OWNER: 3,
        OperatorRole.BREAK_GLASS: -1,
    }
    return max(roles, key=rank.__getitem__)


class _IncidentCreationReceiptRejectedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _reserve_receipt(
    receipt_gate: OperatorRequestReceiptGate,
    request: IncidentCreationRequest,
) -> ReservedOperatorRequestReceipt | None:
    try:
        verified = await receipt_gate.verify_or_committed(incident_creation_receipt_event(request))
    except ValueError as exc:
        raise _IncidentCreationReceiptRejectedError(
            _receipt_rejection_reason(str(exc) or type(exc).__name__)
        ) from exc
    if verified is None:
        return None
    try:
        return await receipt_gate.reserve(verified)
    except ValueError as exc:
        raise _IncidentCreationReceiptRejectedError(
            _receipt_rejection_reason(str(exc) or type(exc).__name__)
        ) from exc


def _receipt_rejection_reason(reason: str) -> str:
    normalized = reason.strip().lower().replace("-", "_")
    if normalized == "missing":
        return "incident_creation_receipt_missing"
    if normalized == "expired":
        return "incident_creation_receipt_expired"
    if normalized == "mismatch":
        return "incident_creation_receipt_mismatch"
    if normalized == "unknown_producer":
        return "incident_creation_receipt_unknown_producer"
    if normalized == "replayed":
        return "incident_creation_receipt_replayed"
    return "incident_creation_receipt_rejected"


__all__ = ["IncidentCreationConsumerBinding", "consume_incident_creations"]
