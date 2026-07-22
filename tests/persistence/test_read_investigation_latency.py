from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fdai.delivery.persistence.read_investigation_latency import (
    StateStoreReadLatencyConfig,
    StateStoreReadLatencyProfileStore,
)
from fdai.shared.providers.read_investigation import ReadLatencySample, ReadToolId
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _sample(index: int, *, at: datetime | None = None) -> ReadLatencySample:
    return ReadLatencySample(
        tool_id=ReadToolId.QUERY_RESOURCE_ACTIVITY,
        transport="rest",
        operation_class="control_plane_activity",
        succeeded=index % 3 != 0,
        queue_duration_ms=index,
        execution_duration_ms=100 + index,
        recorded_at=at or NOW + timedelta(seconds=index),
    )


async def test_latency_samples_survive_concurrent_cross_replica_cas() -> None:
    state = InMemoryStateStore()
    first = StateStoreReadLatencyProfileStore(store=state)
    second = StateStoreReadLatencyProfileStore(store=state)
    await asyncio.gather(
        *(store.append(_sample(index)) for index, store in enumerate((first, second) * 10))
    )
    samples = await first.recent(
        tool_id=ReadToolId.QUERY_RESOURCE_ACTIVITY,
        transport="rest",
        operation_class="control_plane_activity",
        limit=20,
    )
    assert len(samples) == 20
    assert {sample.execution_duration_ms for sample in samples} == set(range(100, 120))
    assert len(state.audit_entries) == 20


async def test_latency_store_applies_retention_and_sample_cap() -> None:
    state = InMemoryStateStore()
    store = StateStoreReadLatencyProfileStore(
        store=state,
        config=StateStoreReadLatencyConfig(max_samples=20, retention_days=1),
    )
    await store.append(_sample(0, at=NOW - timedelta(days=2)))
    for index in range(25):
        await store.append(_sample(index + 1))
    samples = await store.recent(
        tool_id=ReadToolId.QUERY_RESOURCE_ACTIVITY,
        transport="rest",
        operation_class="control_plane_activity",
        limit=20,
    )
    assert len(samples) == 20
    assert all(sample.recorded_at >= NOW for sample in samples)
