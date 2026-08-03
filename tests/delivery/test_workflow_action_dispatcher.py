"""Workflow action dispatch re-enters the typed event pipeline."""

from __future__ import annotations

import pytest

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
    assert envelope.payload["params"] == {"reason": "health probe failed"}
    assert envelope.payload["workflow_action"] == {
        "process_id": "process-1",
        "step_id": "restart",
        "proposal_ref": reference,
    }


async def test_dispatch_rejects_unresolved_parameter_template() -> None:
    bus = InMemoryEventBus()
    dispatcher = EventBusWorkflowActionDispatcher(event_bus=bus, topic="events")

    with pytest.raises(ValueError, match="unresolved parameter templates: reason"):
        await dispatcher.dispatch(
            process_id="process-1",
            correlation_id="corr-1",
            step=RunbookStep(id="restart", action_type="ops.restart-service"),
            target_resource_id="service-1",
            params={"reason": "${change.reason}"},
            context={"requester.principal": "operator-1"},
        )

    assert await _drain(bus) == []


async def test_dispatch_uses_attempt_in_proposal_identity() -> None:
    bus = InMemoryEventBus()
    dispatcher = EventBusWorkflowActionDispatcher(event_bus=bus, topic="events")

    reference = await dispatcher.dispatch(
        process_id="process-1",
        correlation_id="corr-1",
        step=RunbookStep(id="restart", action_type="ops.restart-service"),
        target_resource_id="service-1",
        params={},
        context={"requester.principal": "operator-1"},
        attempt=2,
    )

    assert reference == "process-1:step:restart:attempt:2"
