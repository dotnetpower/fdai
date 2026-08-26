"""Consume versioned Operator intervention requests into Core Incident authority."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fdai.core.incident.intervention import IncidentInterventionService
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai_service_contracts.incident_intervention import IncidentInterventionRequest
from pydantic import ValidationError


@dataclass(frozen=True, slots=True)
class IncidentInterventionConsumerBinding:
    """Bind one request topic to the Core-owned intervention service."""

    request_topic: str
    group_id: str
    service: IncidentInterventionService

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume until the shared Core stop event is set."""

        await consume_incident_interventions(
            bus=bus,
            topic=self.request_topic,
            group_id=self.group_id,
            service=self.service,
            stop=stop,
        )


async def consume_incident_interventions(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    service: IncidentInterventionService,
    stop: asyncio.Event,
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


__all__ = [
    "IncidentInterventionConsumerBinding",
    "consume_incident_interventions",
]
