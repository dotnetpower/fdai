"""Resource-bound regressions for local/testing EventBus adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from fdai.shared.providers.local import LocalEventBus
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def test_testing_event_bus_retention_is_bounded_and_replay_starts_at_retained_base() -> None:
    bus = InMemoryEventBus(max_records_per_topic=100)

    for index in range(10_000):
        await bus.publish("object.event", f"key-{index}", {"sequence": index})

    assert len(bus._records["object.event"]) == 100
    assert bus._base_offsets["object.event"] == 9_900
    stream = bus.subscribe("object.event", "reader")
    first = await anext(stream)
    await stream.aclose()
    assert first.offset == 9_900
    assert first.payload["sequence"] == 9_900


async def test_testing_event_bus_payloads_are_immutable_snapshots() -> None:
    bus = InMemoryEventBus(max_records_per_topic=10)
    payload = {"nested": {"items": [1, 2, 3]}}

    await bus.publish("object.event", "key", payload)
    payload["nested"]["items"].append(4)
    stream = bus.subscribe("object.event", "reader")
    envelope = await anext(stream)
    await stream.aclose()

    assert isinstance(envelope.payload, Mapping)
    assert envelope.payload["nested"]["items"] == [1, 2, 3]


async def test_local_event_bus_expires_abandoned_groups_and_keeps_retention_bounded() -> None:
    bus = LocalEventBus(max_records_per_topic=50, group_idle_seconds=0.001)
    for index in range(10_000):
        stream = bus.subscribe("object.event", f"group-{index}")
        await stream.aclose()

    await asyncio.sleep(0.002)
    for index in range(200):
        await bus.publish("object.event", f"key-{index}", {"sequence": index})

    assert len(bus._offsets) == 0
    assert len(bus._group_locks) == 0
    assert len(bus._records["object.event"]) == 50
    assert bus._base_offsets["object.event"] == 150


async def test_local_event_bus_payloads_are_immutable_snapshots() -> None:
    bus = LocalEventBus(max_records_per_topic=10)
    payload = {"nested": {"items": [1, 2, 3]}}

    await bus.publish("object.event", "key", payload)
    payload["nested"]["items"].append(4)
    stream = bus.subscribe("object.event", "reader")
    envelope = await anext(stream)
    await stream.aclose()

    assert isinstance(envelope.payload, Mapping)
    assert envelope.payload["nested"]["items"] == [1, 2, 3]
