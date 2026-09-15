"""Consume versioned Operator intervention requests into Core Incident authority."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fdai.core.incident.intervention import IncidentInterventionService
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai_service_contracts.incident_intervention import (
    INCIDENT_INTERVENTION_EVENT_TYPE,
    IncidentInterventionAction,
    IncidentInterventionRequest,
)
from pydantic import ValidationError

IncidentInterventionIngress = Callable[[dict[str, Any]], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class IncidentInterventionConsumerBinding:
    """Bind one request topic to the Core-owned intervention service."""

    request_topic: str
    group_id: str
    service: IncidentInterventionService
    ingress: IncidentInterventionIngress | None = None

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume until the shared Core stop event is set."""

        await consume_incident_interventions(
            bus=bus,
            topic=self.request_topic,
            group_id=self.group_id,
            service=self.service,
            stop=stop,
            ingress=self.ingress,
        )


async def consume_incident_interventions(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    service: IncidentInterventionService,
    stop: asyncio.Event,
    ingress: IncidentInterventionIngress | None = None,
) -> None:
    """Apply valid requests before allowing at-least-once delivery to advance."""

    async with subscription(bus, topic, group_id) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            try:
                request = IncidentInterventionRequest.model_validate(envelope.payload)
                if envelope.key != request.incident_id:
                    raise ValueError("incident intervention partition key mismatch")
            except (ValidationError, ValueError):
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "incident_intervention_request_rejected",
                )
                continue
            try:
                await service.apply(request)
                if request.action is IncidentInterventionAction.GUIDANCE and ingress is not None:
                    await ingress(incident_intervention_raw_event(request))
            except KeyError:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "incident_intervention_not_found",
                )
            except PermissionError:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "incident_intervention_unauthorized",
                )
            except ValueError:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "incident_intervention_state_rejected",
                )


def incident_intervention_raw_event(
    request: IncidentInterventionRequest,
) -> dict[str, Any]:
    """Re-enter applied guidance through Huginn without granting action authority."""

    return {
        "event_type": INCIDENT_INTERVENTION_EVENT_TYPE,
        "event_id": request.request_id,
        "idempotency_key": f"incident-intervention:{request.request_id}",
        "correlation_id": request.correlation_id,
        "source": "operator-incident-intervention",
        "resource_ref": request.target_ref,
        "incident_correlation": "none",
        "occurred_at": request.requested_at.isoformat(),
        "attributes": {
            "incident_intervention": {
                "schema_version": request.schema_version,
                "request_id": request.request_id,
                "request_digest": request.request_digest,
                "incident_id": request.incident_id,
                "action": request.action.value,
                "guidance": request.comment,
                "accountable_agent": request.accountable_agent,
                "execution_authority": request.execution_authority,
            }
        },
    }


__all__ = [
    "IncidentInterventionConsumerBinding",
    "consume_incident_interventions",
    "incident_intervention_raw_event",
]
