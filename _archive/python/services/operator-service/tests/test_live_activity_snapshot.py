"""Durable startup snapshot contracts for Live operational activity."""

from __future__ import annotations

from typing import cast

from fdai_operator_service.composition import (
    _live_activity_key,
    _LiveActivitySnapshotLoader,
)
from fdai_operator_service.projections import ProjectionUnavailableError
from fdai_operator_service.streaming import LiveStreamHub
from fdai_service_contracts import AgentActivityQuery, JsonProjection, OperatorReadModel


class _ActivityReadModel:
    query: AgentActivityQuery | None = None

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection:
        self.query = query
        return JsonProjection(
            {
                "items": [
                    {
                        "type": "agent.operational-activity",
                        "activity_id": "inventory.scan:attempt-1:completed",
                        "activity_instance_id": "inventory.scan:attempt-1",
                    }
                ],
                "snapshot_at": "2026-09-14T00:00:00Z",
                "source": "durable-operational-projection",
            }
        )


class _UnavailableActivityReadModel:
    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection:
        del query
        raise ProjectionUnavailableError("activity projection unavailable")


async def test_loader_seeds_activity_and_ready_status_without_delta_sequence() -> None:
    read_model = _ActivityReadModel()
    hub = LiveStreamHub(latest_key=_live_activity_key)
    loader = _LiveActivitySnapshotLoader(
        cast(OperatorReadModel, read_model),
        hub,
    )

    await loader.start()
    subscription = hub.subscribe_deliveries()
    activity = await anext(subscription)
    status = await anext(subscription)

    assert read_model.query == AgentActivityQuery(limit=64)
    assert activity.event.payload["activity_instance_id"] == "inventory.scan:attempt-1"
    assert status.event.payload["status"] == "ready"
    assert activity.sequence is None
    assert status.sequence is None
    assert hub.next_sequence == 1
    await subscription.aclose()


async def test_loader_surfaces_known_projection_failure_as_unavailable_snapshot() -> None:
    hub = LiveStreamHub(latest_key=_live_activity_key)
    loader = _LiveActivitySnapshotLoader(
        cast(OperatorReadModel, _UnavailableActivityReadModel()),
        hub,
    )

    await loader.start()
    status = await anext(hub.subscribe_deliveries())

    assert status.event.payload["status"] == "unavailable"
    assert status.event.payload["reason"] == "durable_projection_unavailable"


async def test_loader_marks_unconfigured_projection_unavailable() -> None:
    hub = LiveStreamHub(latest_key=_live_activity_key)

    await _LiveActivitySnapshotLoader(None, hub).start()
    status = await anext(hub.subscribe_deliveries())

    assert status.event.payload["status"] == "unavailable"
