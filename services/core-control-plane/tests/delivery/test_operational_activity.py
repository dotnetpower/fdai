"""Operational activity publisher and inventory observation tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    ObservedInventorySnapshotStore,
)
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.inventory import InventoryBatch
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryCoverageManifest,
    InventoryFailureCode,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


class _SnapshotStore:
    def __init__(self) -> None:
        self.status = "none"

    async def begin(self, manifest: InventoryCoverageManifest) -> str:
        self.status = "collecting"
        return "attempt-1"

    async def stage(self, attempt_id: str, batch: InventoryBatch) -> None:
        self.status = "staged"

    async def promote(self, attempt_id: str, manifest: InventoryCoverageManifest) -> None:
        self.status = "active"

    async def fail(self, attempt_id: str, failure: InventoryAttemptFailure) -> None:
        self.status = "failed"


class _FailingBus:
    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        raise RuntimeError("broker unavailable")

    def subscribe(self, topic: str, group_id: str):
        async def _empty():
            if False:
                yield EventEnvelope(topic, "", {}, None)

        return _empty()

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        return None


def _manifest() -> InventoryCoverageManifest:
    return InventoryCoverageManifest(
        source="azure-resource-graph",
        scopes=("configured-subscription",),
        resource_types=("resource-group",),
    )


async def test_inventory_observer_publishes_after_durable_transitions() -> None:
    bus = InMemoryEventBus()
    store = _SnapshotStore()
    observed = ObservedInventorySnapshotStore(
        store=store,
        publisher=EventBusOperationalActivityPublisher(event_bus=bus),
    )

    attempt_id = await observed.begin(_manifest())
    assert store.status == "collecting"
    await observed.promote(attempt_id, _manifest())
    await observed.publish_terminal(
        attempt_id=attempt_id,
        source="azure-resource-graph",
        active=True,
        evidence_count=12,
    )
    events = [event async for event in bus.subscribe("aw.pipeline.stages", "test")]

    assert [event.payload["status"] for event in events] == ["started", "completed"]
    assert events[-1].payload["evidence_count"] == 12
    assert events[-1].payload["execution_authority"] is False


async def test_inventory_observer_publishes_bounded_failure_code() -> None:
    bus = InMemoryEventBus()
    observed = ObservedInventorySnapshotStore(
        store=_SnapshotStore(),
        publisher=EventBusOperationalActivityPublisher(event_bus=bus),
    )

    attempt_id = await observed.begin(_manifest())
    await observed.fail(
        attempt_id,
        InventoryAttemptFailure(
            code=InventoryFailureCode.NETWORK_BLOCKED,
            message="transport error",
        ),
    )
    events = [event async for event in bus.subscribe("aw.pipeline.stages", "test")]

    assert events[-1].payload["status"] == "failed"
    assert events[-1].payload["reason_codes"] == ["network_blocked"]
    assert "transport error" not in str(events[-1].payload)


async def test_broker_failure_does_not_rollback_snapshot_transition() -> None:
    store = _SnapshotStore()
    observed = ObservedInventorySnapshotStore(
        store=store,
        publisher=EventBusOperationalActivityPublisher(event_bus=_FailingBus()),
    )

    attempt_id = await observed.begin(_manifest())

    assert attempt_id == "attempt-1"
    assert store.status == "collecting"
