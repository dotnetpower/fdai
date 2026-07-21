from __future__ import annotations

from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


class _ClosableInMemoryEventBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


async def test_multiplex_round_trip_preserves_logical_topic() -> None:
    raw = InMemoryEventBus()
    bus = MultiplexedEventBus(
        bus=raw,
        logical_topics=frozenset({"object.event", "object.verdict"}),
        physical_topic="objects",
    )

    receipt = await bus.publish("object.event", "resource-1", {"value": 1})
    stream = bus.subscribe("object.event", "agent")
    envelope = await anext(stream)

    assert receipt.topic == "object.event"
    assert envelope.topic == "object.event"
    assert envelope.payload == {"value": 1}


async def test_logical_subscriptions_do_not_share_consumer_group() -> None:
    raw = InMemoryEventBus()
    bus = MultiplexedEventBus(
        bus=raw,
        logical_topics=frozenset({"object.event", "object.verdict"}),
        physical_topic="objects",
    )
    event_stream = bus.subscribe("object.event", "same-agent")
    verdict_stream = bus.subscribe("object.verdict", "same-agent")

    await bus.publish("object.event", "one", {"kind": "event"})
    await bus.publish("object.verdict", "two", {"kind": "verdict"})

    assert (await anext(event_stream)).payload["kind"] == "event"
    assert (await anext(verdict_stream)).payload["kind"] == "verdict"


async def test_non_multiplexed_topic_passes_through() -> None:
    raw = InMemoryEventBus()
    bus = MultiplexedEventBus(
        bus=raw,
        logical_topics=frozenset({"object.event"}),
        physical_topic="objects",
    )

    await bus.publish("aw.change.events", "one", {"kind": "raw"})
    assert (await anext(bus.subscribe("aw.change.events", "core"))).topic == ("aw.change.events")


async def test_close_delegates_to_underlying_broker() -> None:
    raw = _ClosableInMemoryEventBus()
    bus = MultiplexedEventBus(
        bus=raw,
        logical_topics=frozenset({"object.event"}),
        physical_topic="objects",
    )

    await bus.close()

    assert raw.close_count == 1
