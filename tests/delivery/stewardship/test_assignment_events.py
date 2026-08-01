from __future__ import annotations

from fdai.delivery.identity import APPLY_HUMAN_ACCESS_ACTION
from fdai.delivery.stewardship.assignment_events import EventBusAssignmentApplyPublisher
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def test_assignment_apply_event_reenters_typed_ingress() -> None:
    bus = InMemoryEventBus()
    publisher = EventBusAssignmentApplyPublisher(bus, "aw.events")

    await publisher.publish(
        case_id="case-1",
        expected_revision=4,
        requester_ref="requester-1",
    )

    records = [record async for record in bus.subscribe("aw.events", "test")]
    assert len(records) == 1
    assert records[0].key == "human-assignment:case-1"
    assert records[0].payload == {
        "idempotency_key": "human-access:case-1:4",
        "correlation_id": "human-assignment:case-1",
        "initiator_principal": "requester-1",
        "operator_initiated": True,
        "action_type": APPLY_HUMAN_ACCESS_ACTION,
        "resource_id": "human-assignment:case-1",
        "resource_type": "human-assignment",
        "event_type": "operator_request",
        "origin_event_type": "human.assignment.iam_apply_requested",
        "params": {"case_id": "case-1", "expected_revision": 4},
    }
