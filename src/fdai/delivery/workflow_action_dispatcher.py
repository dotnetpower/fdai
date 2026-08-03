"""Republish enforce Workflow action steps into typed control-loop ingress."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.runbook.models import RunbookStep
from fdai.shared.providers.event_bus import EventBus

_UNRESOLVED_TEMPLATE = re.compile(r"\$\{[^{}]+\}")


@dataclass(frozen=True, slots=True)
class EventBusWorkflowActionDispatcher:
    """Publish an action proposal without holding executor authority."""

    event_bus: EventBus
    topic: str

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("workflow action topic MUST be non-empty")

    async def dispatch(
        self,
        *,
        process_id: str,
        correlation_id: str,
        step: RunbookStep,
        target_resource_id: str,
        params: Mapping[str, object],
        context: Mapping[str, str],
    ) -> str:
        requester = context.get("requester.principal", "").strip()
        if not requester:
            raise ValueError("enforce workflow action requires requester.principal")
        unresolved = sorted(
            key
            for key, value in params.items()
            if isinstance(value, str) and _UNRESOLVED_TEMPLATE.search(value)
        )
        if unresolved:
            raise ValueError(
                "workflow action has unresolved parameter templates: " + ", ".join(unresolved)
            )
        idempotency_key = f"{process_id}:step:{step.id}:attempt:1"
        await self.event_bus.publish(
            self.topic,
            target_resource_id,
            {
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
                "initiator_principal": requester,
                "operator_initiated": True,
                "action_type": step.action_type,
                "resource_id": target_resource_id,
                "event_type": "operator_request",
                "params": dict(params),
                "workflow_action": {
                    "process_id": process_id,
                    "step_id": step.id,
                    "proposal_ref": idempotency_key,
                },
            },
        )
        return idempotency_key


__all__ = ["EventBusWorkflowActionDispatcher"]
