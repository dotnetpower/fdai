"""Operational activity multiplexing from the stage relay into Live SSE."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from fdai_operator_service.adapters.live_stage_kafka import (
    LiveStageKafkaConfig,
    LiveStageKafkaRelay,
)
from fdai_operator_service.composition import _live_activity_key
from fdai_operator_service.streaming import LiveStreamHub


class _Consumer:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[object] = asyncio.Queue()
        self.commits = 0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def getone(self) -> object:
        return await self.messages.get()

    async def commit(self) -> None:
        self.commits += 1


async def test_operational_activity_reaches_live_and_legacy_agent_hubs() -> None:
    consumer = _Consumer()
    live_hub = LiveStreamHub(latest_key=_live_activity_key)
    agent_hub = LiveStreamHub()
    relay = LiveStageKafkaRelay(
        config=LiveStageKafkaConfig(
            bootstrap_servers="127.0.0.1:19092",
            security_protocol="PLAINTEXT",
        ),
        hub=live_hub,
        agent_hub=agent_hub,
        credential=None,
        consumer_factory=lambda: consumer,  # type: ignore[arg-type]
    )
    live = live_hub.subscribe()
    agent = agent_hub.subscribe()
    waiting_live = asyncio.create_task(anext(live))
    waiting_agent = asyncio.create_task(anext(agent))
    await asyncio.sleep(0)
    payload = {
        "type": "agent.operational-activity",
        "schema_version": "1.0.0",
        "activity_id": "inventory.scan:attempt-1:completed",
        "idempotency_key": "inventory.scan:attempt-1:completed",
        "kind": "inventory.scan",
        "status": "completed",
        "owner_agent": "Huginn",
        "producer": "inventory-sync-job",
        "observed_at": datetime.now(UTC).isoformat(),
        "source": "azure-resource-graph",
        "freshness": "fresh",
        "evidence_count": 1,
        "duration_ms": 2,
        "correlation_id": "attempt-1",
        "reason_codes": [],
        "execution_authority": False,
    }

    await relay.start()
    await consumer.messages.put(SimpleNamespace(value=json.dumps(payload).encode("utf-8")))

    live_activity = await asyncio.wait_for(waiting_live, timeout=0.5)
    agent_activity = await asyncio.wait_for(waiting_agent, timeout=0.5)
    assert live_activity.event_type == "activity"
    assert live_activity.payload["activity_id"] == payload["activity_id"]
    assert agent_activity.event_type == "message"
    assert agent_activity.payload == live_activity.payload
    assert consumer.commits == 1

    await live.aclose()
    await agent.aclose()
    await relay.aclose()
