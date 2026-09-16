"""Consume confirmed Operator requests into the Core-owned Incident registry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from fdai.core.incident import IncidentLifecycleWorkflow, IncidentWorkflowForbiddenError
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai_service_contracts.incident_creation import IncidentCreationRequest
from fdai_service_contracts.operator import OperatorRole
from pydantic import ValidationError


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

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume requests until the shared Core stop event is set."""

        await consume_incident_creations(
            bus=bus,
            topic=self.request_topic,
            group_id=self.group_id,
            workflow=self.workflow,
            stop=stop,
        )


async def consume_incident_creations(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    workflow: IncidentLifecycleWorkflow,
    stop: asyncio.Event,
) -> None:
    """Apply valid confirmed requests before advancing at-least-once delivery."""

    async with subscription(bus, topic, group_id) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            try:
                request = IncidentCreationRequest.model_validate(envelope.payload)
                if envelope.key != request.target_ref:
                    raise ValueError("incident creation partition key mismatch")
                role = _highest_ordinary_role(request.principal_roles)
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


__all__ = ["IncidentCreationConsumerBinding", "consume_incident_creations"]
