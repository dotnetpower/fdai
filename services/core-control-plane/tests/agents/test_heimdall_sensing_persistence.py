"""Equal-workload byte accounting and exact restart semantics for sensing state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import pytest
from fdai.agents import Heimdall, InMemoryBus, load_pantheon
from fdai.core.readiness import DetectionReadinessDimension
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 10, 30, tzinfo=UTC)
STATE = "pantheon/heimdall/sensing-state"


@lru_cache(maxsize=4096)
def _encoded(key: tuple[str, ...]) -> str:
    return json.dumps(key, ensure_ascii=True, separators=(",", ":"))


@lru_cache(maxsize=4096)
def _subject(family: str, identity: str) -> str:
    return f"{STATE}/{family}/" + hashlib.sha256(identity.encode()).hexdigest()


class CountingStore(InMemoryStateStore):
    """Count all state mutations and JSON value traffic, excluding transport framing."""

    def __init__(self) -> None:
        super().__init__()
        self.writes = 0
        self.wire_bytes = 0
        self.fail_key: str | None = None

    async def write_state(self, key: str, value: Mapping[str, Any]) -> None:
        if self.fail_key in (key, "*"):
            raise OSError("injected sensing write failure")
        await super().write_state(key, value)

    def _write_locked(self, key: str, value: Mapping[str, Any]) -> None:
        # Include the unchanged publication claim/CAS path, not just snapshot writes.
        super()._write_locked(key, value)
        self.writes += 1
        self.wire_bytes += len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        )

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        value = await super().read_state(key)
        if value is not None:
            self.wire_bytes += len(
                json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            )
        return value

    def persisted_bytes(self) -> int:
        return sum(
            len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
            for value in self._state.values()
        )


def _snapshot(agent: Heimdall) -> dict[str, Any]:
    return {
        "recent_events": {
            _encoded(key): [list(item) for item in history]
            for key, history in agent._recent_events.items()
        },
        "incident_episode_ids": {
            _encoded(key): value for key, value in agent._incident_episode_ids.items()
        },
        "incident_episode_severities": {
            _encoded(key): value for key, value in agent._incident_episode_severities.items()
        },
        "security_recent": list(agent._security_recent),
        "alert_windows": {key: list(value) for key, value in agent._alert_windows.items()},
        "detection_readiness": {
            resource: {dim: obs.model_dump(mode="json") for dim, obs in observations.items()}
            for resource, observations in agent._detection_readiness.items()
        },
        "detection_readiness_pending": {
            resource + "\0" + pass_id: {
                dim: obs.model_dump(mode="json") for dim, obs in observations.items()
            }
            for (resource, pass_id), observations in agent._detection_readiness_pending.items()
        },
        "detection_readiness_pass_order": {
            resource: [pass_id, observed.isoformat()]
            for resource, (pass_id, observed) in agent._detection_readiness_pass_order.items()
        },
    }


class LegacySnapshotHeimdall(Heimdall):
    async def _persist_state(self) -> None:
        """Frozen pre-optimization write workload, including its 128-subject cutoff."""
        snapshot = _snapshot(self)
        for key in tuple(self._dirty_episode_keys):
            history = self._recent_events.get(key)
            if history is not None:
                await self._state_store.write_state(
                    _subject("episodes", _encoded(key)),
                    {
                        "schema_version": "1.0.0",
                        "revision": len(history),
                        "episode_key": _encoded(key),
                        "history": [list(item) for item in history],
                    },
                )
        for resource in tuple(self._dirty_readiness_resources):
            if resource in self._detection_readiness:
                await self._state_store.write_state(
                    _subject("readiness", resource),
                    {
                        "schema_version": "1.0.0",
                        "revision": 1,
                        "resource_id": resource,
                        "observations": snapshot["detection_readiness"][resource],
                        "pass_order": snapshot["detection_readiness_pass_order"].get(resource),
                    },
                )
        for resource, pass_id in tuple(self._dirty_pending_readiness):
            identity = resource + "\0" + pass_id
            observations = snapshot["detection_readiness_pending"].get(identity)
            if observations is not None:
                await self._state_store.write_state(
                    _subject("readiness-pending", identity),
                    {
                        "schema_version": "1.0.0",
                        "revision": len(observations),
                        "resource_id": resource,
                        "pass_id": pass_id,
                        "observations": observations,
                    },
                )
        if len(self._recent_events) > 128:
            snapshot["recent_events"] = {}
        if len(self._detection_readiness) + len(self._detection_readiness_pending) > 128:
            for field in (
                "detection_readiness",
                "detection_readiness_pending",
                "detection_readiness_pass_order",
            ):
                snapshot[field] = {}
        await self._state_store.write_state(
            STATE, {"schema_version": "1.0.0", "revision": 1, **snapshot}
        )
        self._dirty_episode_keys.clear()
        self._dirty_readiness_resources.clear()
        self._dirty_pending_readiness.clear()


def _event(index: int, *, subject: int = 0, seconds: int = 0) -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": f"incident:{subject}",
        "idempotency_key": f"event:{index}",
        "event_type": "availability.probe_failed",
        "occurred_at": (NOW + timedelta(seconds=seconds)).isoformat(),
        "resource_id": f"service:{subject}",
        "resource_type": "service",
        "severity": "low",
    }


def _agent(store: Any, agent_type: type[Heimdall] = Heimdall, **kwargs: Any) -> Heimdall:
    async def accept_candidate(_candidate: dict[str, Any]) -> bool:
        return True

    return agent_type(
        state_store=store,
        bus=InMemoryBus(load_pantheon()),
        clock=lambda: NOW.timestamp(),
        forecast_clock=lambda: NOW,
        rate_threshold=4,
        incident_candidate_hook=accept_candidate,
        **kwargs,
    )


def _messages(agent: Heimdall) -> list[tuple[str, dict[str, Any]]]:
    return [(message.topic, dict(message.payload)) for message in agent.bus.published]


async def test_same_workload_bytes_writes_and_exact_restart() -> None:
    before_store, after_store = CountingStore(), CountingStore()
    before, after = _agent(before_store, LegacySnapshotHeimdall), _agent(after_store)
    seed = [_event(index, subject=index) for index in range(64)]
    for event in seed:
        await before.on_typed_message("object.event", deepcopy(event))
        await after.on_typed_message("object.event", deepcopy(event))
    duplicate_start = after_store.writes
    for index in range(2_000):
        event = seed[index % len(seed)]
        await before.on_typed_message("object.event", deepcopy(event))
        await after.on_typed_message("object.event", deepcopy(event))
    assert after_store.writes == duplicate_start
    for index in range(1_000):
        event = _event(64 + index, subject=index % 64, seconds=index % 10 + 1)
        await before.on_typed_message("object.event", deepcopy(event))
        await after.on_typed_message("object.event", deepcopy(event))
    changed = _event(10_000, seconds=12)
    changed["severity"] = "critical"
    for event in (changed, _event(10_001, seconds=11), _event(10_002, seconds=-500), changed):
        await before.on_typed_message("object.event", deepcopy(event))
        await after.on_typed_message("object.event", deepcopy(event))
    assert _snapshot(before) == _snapshot(after)
    assert _messages(before) == _messages(after)
    assert len(before_store._audit) == len(after_store._audit)
    assert before.bus.messages_on("object.anomaly")
    metrics = {
        name: {
            "writes": store.writes,
            "wire_bytes": store.wire_bytes,
            "persisted_bytes": store.persisted_bytes(),
        }
        for name, store in (("before", before_store), ("after", after_store))
    }
    expected = _snapshot(after)
    restarted = _agent(after_store)
    assert await restarted.rehydrate() == len(expected["recent_events"])
    assert _snapshot(restarted) == expected
    assert list(restarted._recent_events) == list(after._recent_events)
    writes = after_store.writes
    await restarted.on_typed_message("object.event", deepcopy(changed))
    assert after_store.writes == writes
    assert _snapshot(restarted) == expected
    assert metrics["after"]["wire_bytes"] < metrics["before"]["wire_bytes"]
    assert metrics["after"]["writes"] < metrics["before"]["writes"]
    assert metrics["after"]["persisted_bytes"] > 0
    print(json.dumps(metrics, sort_keys=True))


@pytest.mark.parametrize("subject_limit", [3, 140])
async def test_manifest_preserves_active_membership_not_update_order_or_orphans(
    subject_limit: int,
) -> None:
    store = CountingStore()
    agent = _agent(store)
    agent._max_tracked_keys = subject_limit
    for index in range(subject_limit):
        await agent.on_typed_message("object.event", _event(index, subject=index))
    await agent.on_typed_message("object.event", _event(10, subject=0, seconds=1))
    await agent.on_typed_message("object.event", _event(subject_limit, subject=subject_limit))
    expected = _snapshot(agent)
    restarted = _agent(store)
    await restarted.rehydrate()
    assert _snapshot(restarted) == expected
    assert list(restarted._recent_events) == list(agent._recent_events)
    assert list(restarted._recent_episode_keys) == list(agent._recent_episode_keys)
    assert len(restarted._persisted_sensing_records) == subject_limit + 65


async def test_legacy_full_snapshot_migrates_all_subjects_before_manifest() -> None:
    store = CountingStore()
    agent = _agent(store)
    events = [_event(index, subject=index) for index in range(3)]
    for event in events:
        await agent.on_typed_message("object.event", event)
    legacy = {"schema_version": "1.0.0", "revision": 1, **_snapshot(agent)}
    store._state.clear()
    await store.write_state(STATE, legacy)
    restarted = _agent(store)
    assert await restarted.rehydrate() == 3
    assert _snapshot(restarted) == _snapshot(agent)
    await restarted.on_typed_message("object.event", events[0])
    migrated = _agent(store)
    assert await migrated.rehydrate() == 3
    assert _snapshot(migrated) == _snapshot(agent)


@pytest.mark.parametrize("fail_key", [STATE, "*"])
async def test_failed_manifest_is_retried_and_missing_subject_fails_closed(
    fail_key: str,
) -> None:
    store = CountingStore()
    agent = _agent(store)
    store.fail_key = fail_key
    with pytest.raises(OSError, match="injected"):
        await agent.on_typed_message("object.event", _event(0))
    assert agent._dirty_episode_keys
    store.fail_key = None
    await agent.on_typed_message("object.event", _event(0))
    restarted = _agent(store)
    assert await restarted.rehydrate() == 1
    store._state.pop(_subject("episodes", _encoded(next(iter(agent._recent_events)))))
    with pytest.raises(ValueError, match="missing subject"):
        await _agent(store).rehydrate()


async def test_unknown_manifest_layout_is_not_treated_as_legacy() -> None:
    store = CountingStore()
    await store.write_state(STATE, {"storage_layout": "unknown-layout"})
    with pytest.raises(ValueError, match="unsupported storage layout"):
        await _agent(store).rehydrate()


async def test_cached_acknowledgment_does_not_hide_another_instances_write() -> None:
    store = CountingStore()
    first = _agent(store)
    await first.on_typed_message("object.event", _event(0))
    second = _agent(store)
    await second.rehydrate()
    await second.on_typed_message("object.event", _event(1, seconds=1))
    writes = store.writes
    await first.on_typed_message("object.event", _event(0))
    assert store.writes == writes + 3
    restarted = _agent(store)
    await restarted.rehydrate()
    assert _snapshot(restarted) == _snapshot(first)


async def test_checkpoint_digest_normalizes_integral_numbers_but_rejects_changed_values() -> None:
    store = CountingStore()
    agent = _agent(store)
    await agent.on_typed_message("object.event", _event(0))
    key = _subject("episodes", _encoded(next(iter(agent._recent_events))))
    row = dict(await store.read_state(key))
    row["history"][0][0] = int(row["history"][0][0])
    await store.write_state(key, row)
    assert await _agent(store).rehydrate() == 1
    row["history"][0][0] += 0.125
    await store.write_state(key, row)
    with pytest.raises(ValueError, match="subject digest mismatch; repair required"):
        await _agent(store).rehydrate()


def _readiness(pass_id: str, dim: DetectionReadinessDimension, seconds: int) -> dict[str, Any]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": "readiness:cluster",
        "idempotency_key": f"{pass_id}:{dim.value}",
        "resource_id": "cluster:example",
        "event_type": "detection.readiness.observed",
        "attributes": {
            "pass_id": pass_id,
            "dimension": dim.value,
            "status": "passed",
            "observed_at": (NOW + timedelta(seconds=seconds)).isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "source": "unit-test",
            "evidence_digest": "a" * 64,
        },
    }


async def test_pending_manifest_uses_json_safe_pairs_without_changing_subject_hash() -> None:
    store = CountingStore()
    agent = _agent(store)
    resource, pass_id = 'cluster:"\\example', 'pass:["\\example'
    event = _readiness(pass_id, DetectionReadinessDimension.DISCOVERED, 10)
    event["resource_id"] = resource
    await agent.on_typed_message("object.event", event)
    manifest = await store.read_state(STATE)
    assert manifest is not None
    identity = next(
        entry["identity"]
        for entry in agent._sensing_bucket_entries.values()
        if entry["family"] == "pending"
    )
    assert "\0" not in identity
    assert json.loads(identity) == [resource, pass_id]
    subject = _subject("readiness-pending", resource + "\0" + pass_id)
    assert await store.read_state(subject) is not None
    restarted = _agent(store)
    await restarted.rehydrate()
    assert _snapshot(restarted) == _snapshot(agent)
    # Earlier in-memory manifests remain readable, but new writes always use safe pairs.
    from tests.agents.test_heimdall_bucket_persistence import flat_manifest

    legacy = flat_manifest(agent)
    legacy["pending_readiness_order"] = [resource + "\0" + pass_id]
    await store.write_state(STATE, legacy)
    compatible = _agent(store)
    await compatible.rehydrate()
    assert _snapshot(compatible) == _snapshot(agent)
    await compatible.on_typed_message("object.event", event)
    rewritten = await store.read_state(STATE)
    assert rewritten is not None
    assert "pending_readiness_order" not in rewritten
    assert (
        next(
            entry["identity"]
            for entry in compatible._sensing_bucket_entries.values()
            if entry["family"] == "pending"
        )
        == identity
    )


async def test_readiness_completed_pending_freshness_and_no_resurrection() -> None:
    store = CountingStore()
    agent = _agent(store)
    dimensions = tuple(DetectionReadinessDimension)
    for dim in dimensions:
        await agent.on_typed_message("object.event", _readiness("new", dim, 10))
    partial = _readiness("partial", dimensions[0], 20)
    await agent.on_typed_message("object.event", partial)
    expected = _snapshot(agent)
    restarted = _agent(store)
    await restarted.rehydrate()
    assert _snapshot(restarted) == expected
    assert ("cluster:example", "new") not in restarted._detection_readiness_pending
    writes = store.writes
    for _ in range(1_000):
        await restarted.on_typed_message("object.event", deepcopy(partial))
    assert store.writes == writes
    newer = deepcopy(partial)
    newer["attributes"]["observed_at"] = (NOW + timedelta(seconds=21)).isoformat()
    await restarted.on_typed_message("object.event", newer)
    assert store.writes == writes + 3
    for dim in dimensions:
        await restarted.on_typed_message("object.event", _readiness("old", dim, 0))
    assert restarted.behavior_snapshot()["detection_readiness:stale_pass"] == 1
    again = _agent(store)
    await again.rehydrate()
    assert _snapshot(again) == _snapshot(restarted)
    assert ("cluster:example", "old") not in again._detection_readiness_pending
