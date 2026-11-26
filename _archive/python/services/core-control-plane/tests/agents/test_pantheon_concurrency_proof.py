"""Executable proof of Pantheon runtime independence and concurrent fan-out."""

from __future__ import annotations

import asyncio

from fdai.agents import PANTHEON_NAMES, PantheonRuntime, load_pantheon
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_RAW_TOPIC = "fdai.events"


def test_all_fifteen_agents_have_independent_runtime_consumer_identity() -> None:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic=_RAW_TOPIC,
    )
    pairs = [
        (topic, agent)
        for topic, subscribers in runtime.bridge._subs.items()
        for agent, _handler in subscribers
    ]
    wired_agents = {agent for _topic, agent in pairs}

    assert PANTHEON_NAMES <= wired_agents
    assert len(pairs) == len(set(pairs))
    group_ids = {f"{runtime.bridge.consumer_group_prefix}.{agent}" for agent in PANTHEON_NAMES}
    assert len(group_ids) == 15
    assert (_RAW_TOPIC, "Huginn") in pairs


async def test_multi_message_fanout_does_not_serialize_or_steal() -> None:
    bridge = EventBusBridge(provider=InMemoryEventBus(), registry=load_pantheon())
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    fast_received: list[str] = []
    slow_received: list[str] = []

    async def slow(_topic: str, payload: dict[str, object]) -> None:
        slow_received.append(str(payload["correlation_id"]))
        if len(slow_received) == 1:
            slow_started.set()
            await release_slow.wait()

    async def fast(_topic: str, payload: dict[str, object]) -> None:
        fast_received.append(str(payload["correlation_id"]))

    bridge.subscribe("object.event", "Heimdall", slow)
    bridge.subscribe("object.event", "Forseti", fast)
    expected = [f"corr-{index}" for index in range(3)]
    for correlation_id in expected:
        await bridge.publish(
            "Huginn",
            "object.event",
            {
                "correlation_id": correlation_id,
                "idempotency_key": f"event-{correlation_id}",
                "event_type": "resource.changed",
            },
        )

    run_task = asyncio.create_task(bridge.run())
    try:
        await asyncio.wait_for(slow_started.wait(), timeout=1.0)
        for _ in range(100):
            if fast_received == expected:
                break
            await asyncio.sleep(0)
        assert fast_received == expected
        assert slow_received == [expected[0]]
    finally:
        release_slow.set()
        await run_task

    assert slow_received == expected
    assert bridge.metrics.delivered == 6
