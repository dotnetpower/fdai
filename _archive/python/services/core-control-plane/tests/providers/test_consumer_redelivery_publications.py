from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import pytest
from fdai.agents import EventBusBridge, load_pantheon
from fdai.agents.odin import Odin
from fdai.shared.providers import EventBus, EventEnvelope, StateStore
from fdai.shared.providers.event_bus import EventPublishNotAttemptedError, PublishReceipt
from fdai_service_contracts.compatibility import canonical_digest


class _Harness(Protocol):
    bus: EventBus

    def group(self, suffix: str) -> str: ...

    async def collect(
        self,
        topic: str,
        group: str,
        *,
        expected_count: int,
    ) -> tuple[Any, ...]: ...


@dataclass(slots=True)
class _FailOncePublishBus:
    delegate: EventBus
    fail_topic: str
    failed: bool = False

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if topic == self.fail_topic and not self.failed:
            self.failed = True
            raise EventPublishNotAttemptedError("broker unavailable before send")
        return await self.delegate.publish(topic, key, payload)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        return self.delegate.subscribe(topic, group_id)

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        await self.delegate.dead_letter(topic, key, payload, reason)


async def _stop_bridge(bridge: EventBusBridge, task: asyncio.Task[None]) -> None:
    await bridge.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _wait_for_consumer_state(
    bridge: EventBusBridge,
    consumer_id: str,
    expected: str,
) -> None:
    for _ in range(300):
        if bridge.snapshot()["consumer_states"].get(consumer_id) == expected:
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"{consumer_id} did not reach {expected}")


async def _collect_expected(
    harness: _Harness,
    topic: str,
    group: str,
    *,
    expected_count: int,
) -> tuple[Any, ...]:
    for _ in range(100):
        delivered = await harness.collect(topic, group, expected_count=expected_count)
        if len(delivered) >= expected_count:
            return delivered
        await asyncio.sleep(0.1)
    raise TimeoutError(f"{topic} did not deliver {expected_count} record(s)")


@pytest.mark.asyncio
async def test_odin_checkpointed_decision_republishes_after_bridge_redelivery(
    event_bus_harness: _Harness,
    state_store: StateStore,
) -> None:
    input_topic = "object.arbitration-request"
    output_topic = "object.arbitration-decision"
    correlation_id = f"{event_bus_harness.prefix}-corr-odin-redelivery"
    request = {
        "producer_principal": "Forseti",
        "correlation_id": correlation_id,
        "idempotency_key": f"arbitration-request:{correlation_id}",
        "resource_id": f"{event_bus_harness.prefix}-resource-odin",
        "domains_in_conflict": ["cost", "capacity"],
        "impacts": {"cost": 0.7, "capacity": 0.2},
    }
    failing = _FailOncePublishBus(event_bus_harness.bus, fail_topic=output_topic)
    first_agent = Odin(state_store=state_store)
    first_prefix = event_bus_harness.group("odin-first")
    first_bridge = EventBusBridge(
        provider=failing,
        registry=load_pantheon(),
        max_consumer_restarts=0,
        consumer_group_prefix=first_prefix,
    )
    first_agent.bind_bus(first_bridge)
    first_bridge.subscribe(input_topic, "Odin", first_agent.on_typed_message)
    await event_bus_harness.bus.publish(input_topic, request["correlation_id"], request)

    first_task = asyncio.create_task(first_bridge.run())
    await _wait_for_consumer_state(first_bridge, "Odin:object.arbitration-request", "gave_up")
    assert (
        await event_bus_harness.collect(
            output_topic,
            event_bus_harness.group("odin-empty"),
            expected_count=0,
        )
        == ()
    )
    await _stop_bridge(first_bridge, first_task)

    second_agent = Odin(state_store=state_store)
    second_bridge = EventBusBridge(
        provider=event_bus_harness.bus,
        registry=load_pantheon(),
        consumer_group_prefix=event_bus_harness.group("odin-second"),
    )
    second_agent.bind_bus(second_bridge)
    second_bridge.subscribe(input_topic, "Odin", second_agent.on_typed_message)
    second_task = asyncio.create_task(second_bridge.run())

    delivered = await _collect_expected(
        event_bus_harness,
        output_topic,
        event_bus_harness.group("odin-output"),
        expected_count=1,
    )
    await _stop_bridge(second_bridge, second_task)
    assert len(delivered) == 1
    assert delivered[0].key == correlation_id
    assert delivered[0].payload["idempotency_key"] == f"arbitration-decision:{correlation_id}"
    assert canonical_digest(dict(delivered[0].payload)).startswith("sha256:")


def test_consumer_redelivery_inventory_covers_direct_publish_families() -> None:
    """Inventory families that depend on the same bridge redelivery guarantee."""

    assert {
        "Odin": "arbitration decision checkpoint then publish",
        "Forseti": "verdict publish from deterministic judgment",
        "Thor": "ActionRun publish after dispatch state transition",
        "Vidar": "rollback publish from recovery decision",
        "Norns": "candidate delivery keeps pending rows until flush succeeds",
        "Bragi": "turn publication leaves pending turn outbox until publish succeeds",
        "Saga": "handoff checkpoint remains pending until issue publication succeeds",
    }
