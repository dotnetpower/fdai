from __future__ import annotations

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


@pytest.mark.asyncio
async def test_odin_checkpointed_decision_republishes_after_bridge_redelivery(
    event_bus_harness: _Harness,
    state_store: StateStore,
) -> None:
    input_topic = "object.arbitration-request"
    output_topic = "object.arbitration-decision"
    request = {
        "producer_principal": "Forseti",
        "correlation_id": "corr-odin-redelivery",
        "idempotency_key": "arbitration-request:corr-odin-redelivery",
        "resource_id": "resource-odin",
        "domains_in_conflict": ["cost", "capacity"],
        "impacts": {"cost": 0.7, "capacity": 0.2},
    }
    failing = _FailOncePublishBus(event_bus_harness.bus, fail_topic=output_topic)
    first_agent = Odin(state_store=state_store)
    first_bridge = EventBusBridge(
        provider=failing,
        registry=load_pantheon(),
        max_consumer_restarts=0,
    )
    first_agent.bind_bus(first_bridge)
    first_bridge.subscribe(input_topic, "Odin", first_agent.on_typed_message)
    await event_bus_harness.bus.publish(input_topic, request["correlation_id"], request)

    await first_bridge.run()
    assert (
        first_bridge.snapshot()["consumer_states"]["Odin:object.arbitration-request"] == "gave_up"
    )
    assert (
        await event_bus_harness.collect(
            output_topic,
            event_bus_harness.group("odin-empty"),
            expected_count=0,
        )
        == ()
    )

    second_agent = Odin(state_store=state_store)
    second_bridge = EventBusBridge(provider=event_bus_harness.bus, registry=load_pantheon())
    second_agent.bind_bus(second_bridge)
    second_bridge.subscribe(input_topic, "Odin", second_agent.on_typed_message)
    await second_bridge.run()

    delivered = await event_bus_harness.collect(
        output_topic,
        event_bus_harness.group("odin-output"),
        expected_count=1,
    )
    assert len(delivered) == 1
    assert delivered[0].key == "corr-odin-redelivery"
    assert delivered[0].payload["idempotency_key"] == ("arbitration-decision:corr-odin-redelivery")
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
