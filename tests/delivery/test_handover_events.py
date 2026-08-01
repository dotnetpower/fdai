from __future__ import annotations

from fdai.delivery.handover_events import EventBusHandoverAvailabilityPublisher
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def test_availability_event_is_content_free_and_hashed() -> None:
    bus = InMemoryEventBus()
    publisher = EventBusHandoverAvailabilityPublisher(bus, "aw.events")

    await publisher.publish(subject_ref="subject-1", session_id="session-1")

    records = [item async for item in bus.subscribe("aw.events", "test")]
    assert len(records) == 1
    payload = records[0].payload
    assert payload["event_type"] == "handover.session.available"
    assert payload["content_included"] is False
    assert "subject-1" not in str(payload)
    assert "session-1" not in str(payload)
