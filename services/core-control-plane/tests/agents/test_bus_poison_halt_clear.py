from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.bus_poison_clear import OrderedPoisonHaltClearProcessor
from fdai.agents._framework.bus_poison_halt import halt_key, halt_record_digest
from fdai.agents._framework.registry import load_pantheon
from fdai.shared.providers.testing import InMemoryEventBus, InMemoryStateStore
from fdai_service_contracts.bus_poison_halt_clear import ORDERED_POISON_HALT_CLEAR_TOPIC
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.operator import OperatorPrincipalKind, OperatorRole

_TOPIC = "object.action-run"
_AGENT = "Vidar"
_GROUP = f"fdai-pantheon.{_AGENT}"


async def _drain_bridge(bridge: EventBusBridge) -> None:
    task = asyncio.create_task(bridge.run())
    try:
        await asyncio.wait_for(task, timeout=1)
    finally:
        await bridge.stop()


def _action_run_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "idempotency_key": "action-run-key",
        "correlation_id": "corr-one",
        "resource_id": "resource-one",
        "action_type": "ops.restart",
        "status": "failed",
    }


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_retains_evidence_and_resumes_consumer() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    bridge = EventBusBridge(
        provider=bus,
        registry=load_pantheon(),
        halt_state_store=store,
        handler_max_retries=0,
    )
    deliveries: list[dict[str, object]] = []

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        if not deliveries:
            deliveries.append(payload)
            raise RuntimeError("park first record")
        deliveries.append(payload)

    bridge.subscribe(_TOPIC, _AGENT, handler)
    await bridge.publish("Thor", _TOPIC, _action_run_payload())
    await _drain_bridge(bridge)

    halt = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert halt is not None
    dlq = [envelope async for envelope in bus.subscribe(f"{_TOPIC}.dlq", "dlq-evidence")]
    assert len(dlq) == 1
    request = {
        "request_id": "clear-one",
        "idempotency_key": "clear-key",
        "requested_at": datetime(2026, 10, 1, tzinfo=UTC),
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": halt["revision"],
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": dlq[0].key,
        "parked_record_offset": dlq[0].offset,
        "parked_record_digest": canonical_digest(dict(dlq[0].payload)),
    }
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
    )

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, request)
    assert result.status == "cleared"
    assert bridge.resume_ordered_consumer_after_clear(topic=_TOPIC, agent_name=_AGENT)
    for _ in range(100):
        await asyncio.sleep(0)
        if len(deliveries) == 2:
            break
    await bridge.stop()

    cleared = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert cleared is not None
    assert cleared["status"] == "cleared"
    assert cleared["clear_evidence"]["parked_record_digest"] == request["parked_record_digest"]
    assert await store.verify_chain()
    assert [delivery["idempotency_key"] for delivery in deliveries] == [
        "action-run-key",
        "action-run-key",
    ]
    assert [delivery["correlation_id"] for delivery in deliveries] == ["corr-one", "corr-one"]


@pytest.mark.asyncio
async def test_ordered_poison_halt_clear_rejects_stale_or_missing_evidence() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    await store.write_state(
        halt_key(_GROUP, _TOPIC),
        {
            "schema_version": "1.0.0",
            "revision": 3,
            "status": "halted",
            "consumer_id": f"{_AGENT}:{_TOPIC}",
            "group_id": _GROUP,
            "topic": _TOPIC,
            "partition_key": "resource-one",
            "offset": 0,
        },
    )
    halt = await store.read_state(halt_key(_GROUP, _TOPIC))
    assert halt is not None
    processor = OrderedPoisonHaltClearProcessor(
        bus=bus,
        halt_state_store=store,
        audit_store=store,
    )
    request: dict[str, Any] = {
        "request_id": "clear-two",
        "idempotency_key": "clear-key-two",
        "requested_at": datetime(2026, 10, 1, tzinfo=UTC),
        "principal_id": "owner-one",
        "principal_kind": OperatorPrincipalKind.HUMAN,
        "principal_roles": (OperatorRole.OWNER,),
        "group_id": _GROUP,
        "agent_name": _AGENT,
        "topic": _TOPIC,
        "halt_revision": 2,
        "halt_record_digest": halt_record_digest(halt),
        "parked_record_topic": f"{_TOPIC}.dlq",
        "parked_record_key": "missing",
        "parked_record_offset": 0,
        "parked_record_digest": "sha256:" + "a" * 64,
    }

    result = await processor.handle(ORDERED_POISON_HALT_CLEAR_TOPIC, request)

    assert result == result.__class__("rejected", halted=True, reason="parked_missing")
    assert (await store.read_state(halt_key(_GROUP, _TOPIC)))["status"] == "halted"  # type: ignore[index]
