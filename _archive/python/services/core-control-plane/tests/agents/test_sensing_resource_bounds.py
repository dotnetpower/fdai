from __future__ import annotations

import builtins
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fdai.agents._framework import huginn_dedup
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.huginn_dedup import HuginnDedupJournal, request_digest
from fdai.agents._framework.loki_reservations import LokiReservationJournal
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.freyr import Freyr
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.loki import Loki
from fdai.agents.njord import Njord
from fdai.shared.providers.cost_governance import CostAnalysisSample
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2028, 1, 2, tzinfo=UTC)


class CountingStateStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self.read_state_calls = 0
        self.read_states_calls = 0
        self.write_sizes: list[int] = []

    async def read_state(self, key: str):
        self.read_state_calls += 1
        return await super().read_state(key)

    async def read_states(self, prefix: str, *, limit: int):
        self.read_states_calls += 1
        return await super().read_states(prefix, limit=limit)

    async def write_state(self, key: str, value):
        self.write_sizes.append(len(json.dumps(value, sort_keys=True, default=str)))
        await super().write_state(key, value)


def _raw_event(key: str) -> dict[str, Any]:
    return {
        "idempotency_key": key,
        "event_id": key,
        "correlation_id": f"corr:{key}",
        "event_type": "unit.test",
        "source": "unit-test",
        "resource_id": f"resource:{key}",
    }


async def test_huginn_terminal_receipts_are_compacted_after_replay_window() -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=8, clock=lambda: NOW)

    for index in range(10_000):
        raw = _raw_event(f"event:{index}")
        digest = request_digest(raw)
        claim = await journal.claim(
            idempotency_key=str(raw["idempotency_key"]),
            request_digest=digest,
            payload=raw,
            change_projection=None,
        )
        assert not claim.duplicate
        await journal.complete(idempotency_key=str(raw["idempotency_key"]), request_digest=digest)

    retained, total = await store.read_state_page(
        "pantheon/huginn/ingress-dedup/terminal/", limit=100
    )
    assert total == 32
    assert len(retained) == 32
    recent = _raw_event("event:9999")
    duplicate = await journal.claim(
        idempotency_key="event:9999",
        request_digest=request_digest(recent),
        payload=recent,
        change_projection=None,
    )
    assert duplicate.duplicate is True


async def test_huginn_full_shard_eviction_does_not_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=1, clock=lambda: NOW)
    first = _raw_event("first")
    claim = await journal.claim(
        idempotency_key="first",
        request_digest=request_digest(first),
        payload=first,
        change_projection=None,
    )
    assert not claim.duplicate
    await journal.complete(idempotency_key="first", request_digest=request_digest(first))

    def fail_sorted(*args: object, **kwargs: object) -> object:
        raise AssertionError("hot shard eviction must not call sorted")

    monkeypatch.setattr(builtins, "sorted", fail_sorted)
    second = _raw_event("second")
    claim = await journal.claim(
        idempotency_key="second",
        request_digest=request_digest(second),
        payload=second,
        change_projection=None,
    )
    assert not claim.duplicate


async def test_huginn_recovery_reads_terminal_page_not_every_shard() -> None:
    store = CountingStateStore()
    journal = HuginnDedupJournal(store, capacity=64, clock=lambda: NOW)
    for index in range(512):
        await store.write_state(
            f"pantheon/huginn/ingress-dedup/terminal/{index:04d}",
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "idempotency_key": f"event:{index}",
                "request_digest": "sha256:" + "1" * 64,
                "status": "published",
            },
        )

    keys = await journal.published_keys()

    assert len(keys) == 64
    assert store.read_states_calls == 1
    assert store.read_state_calls == 1


async def test_huginn_shard_recovery_keeps_completion_order_without_repeated_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    # Fewer published keys than capacity read every shard, the path a live start stalled on.
    journal = HuginnDedupJournal(store, capacity=4096, clock=lambda: NOW)
    keys = [f"event:{index}" for index in range(1500)]
    for key in keys:
        raw = _raw_event(key)
        digest = request_digest(raw)
        await journal.claim(
            idempotency_key=key, request_digest=digest, payload=raw, change_projection=None
        )
        await journal.complete(idempotency_key=key, request_digest=digest)

    def fail_min(*args: object, **kwargs: object) -> object:
        raise AssertionError("recovery must not select each key with min, which is quadratic")

    # A module global shadows the builtin only inside the journal module.
    monkeypatch.setattr(huginn_dedup, "min", fail_min, raising=False)
    recovered = await journal.published_keys()

    assert recovered == tuple(keys)


async def test_huginn_lock_map_is_bounded_when_oldest_lock_is_held() -> None:
    huginn = Huginn(dedup_capacity=3)
    held = huginn._lock_for_key("held")  # noqa: SLF001
    await held.acquire()
    try:
        for index in range(10_000):
            huginn._lock_for_key(f"key:{index}")  # noqa: SLF001
        assert len(huginn._ingress_locks) <= huginn._dedup_capacity + 1  # noqa: SLF001
    finally:
        held.release()


async def test_heimdall_publication_locks_are_reclaimed_and_fences_store_digests() -> None:
    store = InMemoryStateStore()
    heimdall = Heimdall(state_store=store)
    heimdall.bind_bus(InMemoryBus(registry=load_pantheon(), handler_timeout=None))
    large_payload = {
        "producer_principal": "Heimdall",
        "correlation_id": "corr:large",
        "idempotency_key": "publication:large",
        "blob": "x" * 10_000,
    }

    assert await heimdall._publish_once("object.anomaly", large_payload) is True  # noqa: SLF001

    assert heimdall._publication_locks == {}  # noqa: SLF001
    (row,) = await store.read_states("pantheon/heimdall/publications/", limit=10)
    assert row["state"] == "published"
    assert "payload" not in row
    assert row["payload_digest"].startswith("sha256:")
    assert "x" * 100 not in json.dumps(row)


async def test_heimdall_compact_persistence_writes_changed_episode_only() -> None:
    store = CountingStateStore()
    heimdall = Heimdall(state_store=store, rate_threshold=2)
    for index in range(10_000):
        key = (f"resource:{index}", "unit.event", "corr", "correlate", "event")
        heimdall._recent_events[key] = __import__("collections").deque(  # noqa: SLF001
            [(float(index), "high", f"evidence:{index}")],
            maxlen=4,
        )
    changed = ("resource:changed", "unit.event", "corr", "correlate", "event")
    heimdall._recent_events[changed] = __import__("collections").deque(  # noqa: SLF001
        [(1.0, "high", "evidence:changed")],
        maxlen=4,
    )
    heimdall._dirty_episode_keys.add(changed)  # noqa: SLF001

    await heimdall._persist_state()  # noqa: SLF001

    assert max(store.write_sizes) < 5_000


async def test_freyr_resource_locks_and_sample_fences_are_bounded() -> None:
    store = InMemoryStateStore()
    freyr = Freyr(state_store=store)
    for index in range(10_000):
        async with freyr._resource_lock(f"resource:{index}"):  # noqa: SLF001
            pass
        await freyr._complete_sample(  # noqa: SLF001
            f"sample:{index}",
            f"resource:{index}",
            NOW.isoformat(),
        )

    _rows, total = await store.read_state_page("pantheon/freyr/accepted-samples/", limit=3000)
    assert freyr._resource_locks == {}  # noqa: SLF001
    assert len(freyr._accepted_sample_keys) == 2048  # noqa: SLF001
    assert total == 2048


async def test_freyr_cost_evidence_updates_in_place_with_bounded_retention() -> None:
    freyr = Freyr()
    for index in range(512):
        freyr._cost_evidence[f"resource:{index}"] = (  # noqa: SLF001
            f"evidence:{index}",
            NOW + timedelta(seconds=index),
            "corr",
        )
    evidence_id = id(freyr._cost_evidence)  # noqa: SLF001

    await freyr._retain_cost_evidence(  # noqa: SLF001
        {
            "resource_id": "resource:new",
            "id": "evidence:new",
            "correlation_id": "corr",
            "observed_at": (NOW + timedelta(hours=2)).isoformat(),
        }
    )

    assert id(freyr._cost_evidence) == evidence_id  # noqa: SLF001
    assert len(freyr._cost_evidence) == 1  # noqa: SLF001


def _cost_sample(index: int) -> CostAnalysisSample:
    return CostAnalysisSample(
        scope_id=f"scope:{index}",
        resource_id=f"resource:{index}",
        amount_usd=Decimal("100"),
        correlation_id=f"corr:{index}",
        observed_at=NOW + timedelta(seconds=index),
        source_authority="unit-test",
        completeness=Decimal("1"),
        ontology_release_digest="sha256:" + "a" * 64,
    )


async def test_njord_scope_locks_fences_and_sample_maps_are_bounded() -> None:
    store = InMemoryStateStore()
    njord = Njord(state_store=store)
    latest_id = id(njord._latest)  # noqa: SLF001
    counts_id = id(njord._counts)  # noqa: SLF001

    for index in range(10_000):
        sample = _cost_sample(index)
        async with njord._scope_lock(sample.scope_id):  # noqa: SLF001
            pass
        await njord._remember_sample(sample)  # noqa: SLF001
        await njord._complete_sample(  # noqa: SLF001
            f"sample:{index}",
            sample,
            sample_digest="sha256:" + f"{index:064x}"[-64:],
        )

    _rows, total = await store.read_state_page("pantheon/njord/accepted-samples/", limit=3000)
    assert njord._scope_locks == {}  # noqa: SLF001
    assert id(njord._latest) == latest_id  # noqa: SLF001
    assert id(njord._counts) == counts_id  # noqa: SLF001
    assert len(njord._latest) == 512  # noqa: SLF001
    assert len(njord._accepted_sample_keys) == 2048  # noqa: SLF001
    assert len(njord._accepted_sample_digests) == 2048  # noqa: SLF001
    assert total == 2048


async def test_loki_publication_locks_and_held_rows_are_bounded() -> None:
    store = InMemoryStateStore()
    loki = Loki(state_store=store)
    for index in range(10_000):
        async with loki._publication_lock(f"experiment:{index}"):  # noqa: SLF001
            pass
    for index in range(300):
        await loki.propose_experiment(
            experiment_id=f"held:{index}",
            action_type="tool.run-chaos-experiment",
            targets=(f"target:{index}",),
            correlation_id=f"corr:{index}",
        )

    _rows, total = await store.read_state_page("pantheon/loki/held-proposals/", limit=400)
    restarted = Loki(state_store=store)
    await restarted.rehydrate()

    assert loki._publication_locks == {}  # noqa: SLF001
    assert total == 256
    assert len(restarted._held_proposals) == 256  # noqa: SLF001


async def test_loki_reservation_journal_rejects_unbounded_blast_radius() -> None:
    store = InMemoryStateStore()

    with pytest.raises(ValueError, match="blast-radius cap"):
        LokiReservationJournal(store, blast_radius_cap=257)
