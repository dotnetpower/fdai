from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.learning import PostTurnReviewInput
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.read_api.routes.post_turn_event_bus import EventBusPostTurnReviewIntake
from fdai.shared.providers.testing import InMemoryEventBus


async def test_intake_publishes_bragi_owned_object_turn() -> None:
    bus = InMemoryEventBus()
    intake = EventBusPostTurnReviewIntake(bus=bus)
    iterator = bus.subscribe("object.turn", "test-consumer")
    review_input = PostTurnReviewInput(
        review_id="review-1",
        principal_scope="principal-hash-1",
        operator_turn_id="turn-operator-1",
        assistant_turn_id="turn-assistant-1",
        completed_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    await intake.submit(review_input)
    envelope = await anext(iterator)

    assert envelope.payload["producer_principal"] == "Bragi"
    assert envelope.payload["kind"] == "post_turn_review"
    assert envelope.payload["review"]["review_id"] == "review-1"


async def test_intake_round_trips_through_shared_physical_topic() -> None:
    physical_bus = InMemoryEventBus()
    object_bus = MultiplexedEventBus(
        bus=physical_bus,
        logical_topics=frozenset({"object.turn"}),
        physical_topic="pantheon.objects",
    )
    intake = EventBusPostTurnReviewIntake(bus=object_bus)
    iterator = object_bus.subscribe("object.turn", "norns")

    await intake.submit(
        PostTurnReviewInput(
            review_id="review-multiplex-1",
            principal_scope="principal-hash-1",
            operator_turn_id="turn-operator-1",
            assistant_turn_id="turn-assistant-1",
            completed_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
    )
    envelope = await anext(iterator)

    assert envelope.topic == "object.turn"
    assert envelope.payload["review"]["review_id"] == "review-multiplex-1"
