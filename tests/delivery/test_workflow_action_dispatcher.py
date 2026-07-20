"""Workflow action dispatch re-enters the typed event pipeline."""

from __future__ import annotations

from fdai.core.runbook.models import RunbookStep
from fdai.delivery.workflow_action_dispatcher import EventBusWorkflowActionDispatcher
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def _drain(bus: InMemoryEventBus) -> list[object]:
    items: list[object] = []
    async for item in bus.subscribe("events", "test"):
        items.append(item)
    return items


async def test_dispatch_publishes_idempotent_operator_request() -> None:
    bus = InMemoryEventBus()
    dispatcher = EventBusWorkflowActionDispatcher(event_bus=bus, topic="events")

    reference = await dispatcher.dispatch(
        process_id="process-1",
        correlation_id="corr-1",
        step=RunbookStep(id="restart", action_type="ops.restart-service"),
        target_resource_id="service-1",
        params={"reason": "health probe failed"},
        context={"requester.principal": "operator-1"},
    )

    envelope = (await _drain(bus))[0]
    assert reference == "process-1:step:restart:attempt:1"
    assert envelope.key == "service-1"
    assert envelope.payload["event_type"] == "operator_request"
    assert envelope.payload["correlation_id"] == "corr-1"
    assert envelope.payload["initiator_principal"] == "operator-1"
    assert envelope.payload["params"]["process_id"] == "process-1"
