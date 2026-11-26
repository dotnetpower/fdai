from __future__ import annotations

import asyncio

from fdai.delivery.probe_failure_streak import StateStoreProbeFailureStreakSource
from fdai.shared.providers.blast_probe import ProbeQuery
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _query() -> ProbeQuery:
    return ProbeQuery(
        probe_id="vm_traffic_last_5m",
        target_ref="resource:private-example",
        deadline_seconds=1,
    )


async def test_failure_streak_is_atomic_audited_and_content_free() -> None:
    store = InMemoryStateStore()
    source = StateStoreProbeFailureStreakSource(store)

    results = await asyncio.gather(*(source.record_failure(_query()) for _ in range(10)))

    assert sorted(results) == list(range(1, 11))
    assert await source.get(_query()) == 10
    assert len(store.audit_entries) == 10
    rendered = repr(store.audit_entries)
    assert "resource:private-example" not in rendered
    assert "vm_traffic_last_5m" not in rendered
    assert all(entry["entry"]["execution_authority"] is False for entry in store.audit_entries)


async def test_success_resets_only_an_existing_nonzero_streak() -> None:
    store = InMemoryStateStore()
    source = StateStoreProbeFailureStreakSource(store)

    await source.record_success(_query())
    assert store.audit_entries == ()
    assert await source.record_failure(_query()) == 1
    await source.record_success(_query())

    assert await source.get(_query()) == 0
    assert store.audit_entries[-1]["entry"]["transition"] == "success"
    assert store.audit_entries[-1]["entry"]["streak"] == 0
