"""Typed event-bus publisher for governed Workflow action proposals."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.runbook.models import RunbookStep
from fdai.shared.providers.event_bus import EventBus


@dataclass(frozen=True, slots=True)
class EventBusWorkflowActionDispatcher:
    """Republish one Workflow step into the ordinary operator-request ingress."""

    event_bus: EventBus
    topic: str

    async def dispatch(
        self,
        *,
        process_id: str,
        correlation_id: str,
        step: RunbookStep,
        target_resource_id: str,
        params: Mapping[str, object],
        context: Mapping[str, str],
        attempt: int = 1,
    ) -> str:
        """Publish one immutable proposal and return its stable identity."""

        if attempt < 1:
            raise ValueError("workflow action attempt MUST be positive")
        proposal_ref = f"{process_id}:step:{step.id}:attempt:{attempt}"
        initiator = (
            context.get("workflow.requester_principal")
            or context.get("event.payload.operator_request.initiator_principal")
            or "fdai.workflow"
        )
        payload = {
            "schema_version": "1.0.0",
            "event_type": "operator_request",
            "operator_initiated": True,
            "idempotency_key": proposal_ref,
            "correlation_id": correlation_id,
            "initiator_principal": initiator,
            "action_type": step.action_type,
            "params": dict(params),
            "resource_id": target_resource_id,
            "resource_type": context.get("event.payload.resource.resource_type"),
            "workflow_action": {
                "process_id": process_id,
                "step_id": step.id,
                "proposal_ref": proposal_ref,
                "attempt": attempt,
            },
        }
        await self.event_bus.publish(self.topic, target_resource_id, payload)
        return proposal_ref


__all__ = ["EventBusWorkflowActionDispatcher"]
