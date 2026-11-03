"""Superseded Heimdall checkpoint rows are reclaimed only when provably unreachable."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest
from fdai.agents._framework import heimdall_checkpoint_gc as gc
from fdai.agents._framework.heimdall_sensing_persistence import MANIFEST_PREFIX, VERSION_PREFIX

from tests.agents.test_heimdall_sensing_persistence import (
    NOW,
    STATE,
    CountingStore,
    _agent,
    _event,
    _snapshot,
)

LATER = NOW + timedelta(days=1)


class AgedStore(CountingStore):
    """Track last-write times so reclamation can honour its minimum row age."""

    def __init__(self) -> None:
        super().__init__()
        self.clock = NOW
        self.written_at: dict[str, Any] = {}

    def _write_locked(self, key: str, value: Any) -> None:
        super()._write_locked(key, value)
        self.written_at[key] = self.clock

    async def read_state_keys_before(
        self, prefix: str, *, before: Any, after: str = "", limit: int = 128
    ) -> tuple[str, ...]:
        return tuple(
            key
            for key in sorted(self._state)
            if key.startswith(prefix) and key > after and self.written_at[key] < before
        )[:limit]


async def _churned(store: AgedStore, subjects: int = 6, rounds: int = 8) -> Any:
    agent = _agent(store)
    agent._max_tracked_keys = subjects
    for round_index in range(rounds):
        for subject in range(subjects):
            await agent.on_typed_message(
                "object.event",
                _event(round_index * 100 + subject, subject=subject + round_index, seconds=1),
            )
    return agent


def _rows(store: AgedStore) -> set[str]:
    return {
        key
        for key in store._state
        if key.startswith((VERSION_PREFIX, MANIFEST_PREFIX, f"{STATE}/episodes/"))
    }


async def _drain(agent: Any) -> int:
    total = 0
    while reclaimed := await gc.collect_unreachable_checkpoint_rows(agent, now=LATER):
        total += reclaimed
    return total


async def test_reclaimed_checkpoint_restores_exactly_and_only_unreachable_rows_go() -> None:
    store = AgedStore()
    agent = await _churned(store)
    expected = _snapshot(agent)
    reachable = gc.reachable_from_memory(agent)
    assert reachable is not None
    assert await gc.reachable_from_store(store) == reachable
    before = _rows(store)

    reclaimed = await _drain(agent)

    assert reclaimed > 0
    assert _rows(store) == before & reachable
    assert reachable <= set(store._state) | {STATE}
    restarted = _agent(store)
    assert await restarted.rehydrate() == len(expected["recent_events"])
    assert _snapshot(restarted) == expected


async def test_rows_younger_than_the_minimum_age_are_kept() -> None:
    store = AgedStore()
    agent = await _churned(store)
    before = _rows(store)

    assert await gc.collect_unreachable_checkpoint_rows(agent, now=NOW) == 0
    assert _rows(store) == before


async def test_a_checkpoint_advanced_by_another_writer_stops_reclamation() -> None:
    store = AgedStore()
    agent = await _churned(store)
    root = deepcopy(dict(await store.read_state(STATE)))
    root["next_ordinal"] += 1
    await store.write_state(STATE, root)
    before = _rows(store)

    assert await gc.collect_unreachable_checkpoint_rows(agent, now=LATER) == 0
    assert _rows(store) == before


async def test_legacy_layout_is_never_reclaimed() -> None:
    store = AgedStore()
    agent = await _churned(store)
    agent._sensing_trie_layout = False
    before = _rows(store)

    assert gc.reachable_from_memory(agent) is None
    assert await gc.collect_unreachable_checkpoint_rows(agent, now=LATER) == 0
    assert _rows(store) == before


async def test_store_without_age_reads_is_left_alone() -> None:
    store = CountingStore()
    agent = await _churned(store)  # type: ignore[arg-type]
    before = set(store._state)

    assert await gc.collect_unreachable_checkpoint_rows(agent, now=LATER) == 0
    assert set(store._state) == before


async def test_maintenance_tick_reclaims_and_counts_rows() -> None:
    store = AgedStore()
    agent = await _churned(store)
    store.clock = NOW - timedelta(days=2)
    for key in store.written_at:
        store.written_at[key] = NOW - timedelta(days=2)
    before = len(_rows(store))

    await agent.maintenance_tick()

    assert len(_rows(store)) < before
    assert agent.behavior_snapshot().get("checkpoint_gc:rows_reclaimed", 0) > 0


@pytest.mark.parametrize("seconds", [1, 2])
async def test_self_correlated_inventory_observation_is_not_tracked(seconds: int) -> None:
    store = AgedStore()
    agent = _agent(store)
    event = {
        "producer_principal": "Huginn",
        "correlation_id": f"inventory-snapshot:{seconds}",
        "idempotency_key": f"inventory-snapshot:{seconds}",
        "event_type": "inventory.resource_observed",
        "occurred_at": NOW.isoformat(),
        "resource_id": "resource-1",
        "resource_type": "compute.vm",
        "severity": "low",
    }

    await agent.on_typed_message("object.event", event)

    assert not agent._recent_events
    assert store.writes == 0

    event["correlation_id"] = "shared-correlation"
    await agent.on_typed_message("object.event", event)

    assert len(agent._recent_events) == 1
