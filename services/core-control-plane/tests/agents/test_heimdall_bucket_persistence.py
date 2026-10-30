"""Fixed-bucket checkpoint bounds compared with the former flat manifest."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
from fdai.agents import Heimdall
from fdai.agents._framework.heimdall_sensing_persistence import (
    BUCKET_COUNT,
    BUCKET_PREFIX,
    SUBJECT_LAYOUT,
    checkpoint_digest,
    write_changed_state,
)

from tests.agents.test_heimdall_sensing_persistence import (
    NOW,
    STATE,
    CountingStore,
    _agent,
    _encoded,
    _event,
    _snapshot,
    _subject,
)


def flat_manifest(agent: Heimdall) -> dict[str, Any]:
    snapshot = _snapshot(agent)
    identities = list(snapshot["recent_events"])
    ready = list(snapshot["detection_readiness"])
    pending = list(snapshot["detection_readiness_pending"])
    keys = [
        *(_subject("episodes", identity) for identity in identities),
        *(_subject("readiness", resource) for resource in ready),
        *(_subject("readiness-pending", identity) for identity in pending),
    ]
    return {
        "schema_version": "1.0.0",
        "revision": 1,
        "storage_layout": SUBJECT_LAYOUT,
        "subject_digest": checkpoint_digest(agent, keys),
        "episode_order": identities,
        "readiness_order": ready,
        "pending_readiness_order": [
            json.dumps(identity.split("\0", 1), ensure_ascii=True, separators=(",", ":"))
            for identity in pending
        ],
        **{
            field: snapshot[field]
            for field in (
                "incident_episode_ids",
                "incident_episode_severities",
                "security_recent",
                "alert_windows",
                "detection_readiness_pass_order",
            )
        },
    }


class FlatManifestHeimdall(Heimdall):
    async def _persist_state(self) -> None:
        """Frozen episode-only flat checkpoint workload, before bucket sharding."""
        assert not self._detection_readiness and not self._detection_readiness_pending
        if not getattr(self, "_sensing_subject_layout", False):
            self._dirty_episode_keys.update(self._recent_events)
        for key in tuple(self._dirty_episode_keys):
            history = self._recent_events.get(key)
            if history is not None:
                await write_changed_state(
                    self,
                    _subject("episodes", _encoded(key)),
                    {
                        "schema_version": "1.0.0",
                        "revision": len(history),
                        "episode_key": _encoded(key),
                        "history": [list(item) for item in history],
                    },
                )
        await write_changed_state(self, STATE, flat_manifest(self))
        self._sensing_subject_layout = True
        self._dirty_episode_keys.clear()


def seed_subjects(agent: Heimdall, count: int) -> None:
    agent._max_tracked_keys = count
    for index in range(count):
        key = (
            f"service:{index}",
            "availability.probe_failed",
            f"incident:{index}",
            "correlate",
            "event",
        )
        agent._episode_history(key).append((NOW.timestamp(), "low", f"event:{index}"))
        agent._dirty_episode_keys.add(key)


def buckets(store: CountingStore) -> dict[str, Any]:
    return {
        key: deepcopy(value) for key, value in store._state.items() if key.startswith(BUCKET_PREFIX)
    }


@pytest.mark.parametrize("count", [2_048, 4_096, 10_000, 20_000])
async def test_fixed_root_and_only_touched_hash_buckets(count: int) -> None:
    store = CountingStore()
    agent = _agent(store)
    seed_subjects(agent, count)
    await agent._persist_state()
    root = await store.read_state(STATE)
    assert root is not None
    assert len(json.dumps(root, separators=(",", ":")).encode()) < 512
    previous = buckets(store)
    first_order = list(agent._recent_events)
    writes = store.writes
    await agent.on_typed_message("object.event", _event(count + 1, subject=count // 2))
    changed = {key for key, value in buckets(store).items() if previous[key] != value}
    assert len(changed) == 1
    assert store.writes == writes + 3
    assert list(agent._recent_events) == first_order
    previous = buckets(store)
    writes = store.writes
    await agent.on_typed_message("object.event", _event(count + 1, subject=count // 2))
    assert store.writes == writes
    assert buckets(store) == previous
    await agent.on_typed_message("object.event", _event(count + 2, subject=count + 2))
    changed = {key for key, value in buckets(store).items() if previous[key] != value}
    assert 1 <= len(changed) <= 2
    restarted = _agent(store)
    assert await restarted.rehydrate() == count
    assert _snapshot(restarted) == _snapshot(agent)
    assert list(restarted._recent_events) == list(agent._recent_events)
    assert first_order[0] not in restarted._recent_events
    print(
        json.dumps(
            {
                "subjects": count,
                "root_bytes": len(json.dumps(root).encode()),
                "largest_bucket_bytes": max(len(json.dumps(v).encode()) for v in previous.values()),
                "eviction_changed_buckets": len(changed),
            },
            sort_keys=True,
        )
    )


async def test_existing_flat_checkpoint_migrates_without_losing_state_or_order() -> None:
    store = CountingStore()
    old = _agent(store, agent_type=FlatManifestHeimdall)
    seed_subjects(old, 2_048)
    await old._persist_state()
    restarted = _agent(store)
    assert await restarted.rehydrate() == 2_048
    assert _snapshot(restarted) == _snapshot(old)
    assert list(restarted._recent_events) == list(old._recent_events)
    await restarted._persist_state()
    migrated = _agent(store)
    assert await migrated.rehydrate() == 2_048
    assert _snapshot(migrated) == _snapshot(old)
    assert list(migrated._recent_events) == list(old._recent_events)
    assert len(buckets(store)) == BUCKET_COUNT


@pytest.mark.parametrize("stage", ["bucket", "root"])
async def test_partial_bucket_checkpoint_fails_closed_then_retries(stage: str) -> None:
    store = CountingStore()
    agent = _agent(store)
    seed_subjects(agent, 8)
    await agent._persist_state()
    key = _subject("episodes", _encoded(next(iter(agent._recent_events))))
    slot_key = next(name for name, body in buckets(store).items() if key in body["entries"])
    store.fail_key = STATE if stage == "root" else slot_key
    with pytest.raises(OSError, match="injected"):
        await agent.on_typed_message("object.event", _event(100, seconds=1))
    with pytest.raises(ValueError, match="digest mismatch; repair required"):
        await _agent(store).rehydrate()
    store.fail_key = None
    await agent._persist_state()
    restarted = _agent(store)
    assert await restarted.rehydrate() == 8
    assert _snapshot(restarted) == _snapshot(agent)
    assert list(restarted._recent_events) == list(agent._recent_events)
