"""Receipt-time changes must not turn an identical observation into a key collision."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.huginn_dedup import _terminal_key, request_digest
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_huginn_discovery import _canonical_event


@pytest.mark.parametrize("restart", [False, True])
async def test_same_observation_with_new_transport_receipt_is_a_duplicate(restart):
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    huginn = Huginn(bus=bus, state_store=store)
    raw = {**_canonical_event(), "ingested_at": "2026-07-18T01:02:04+00:00"}
    assert await huginn.ingest(raw) is not None
    if restart:
        huginn = Huginn(bus=bus, state_store=store)
    repeated = {**raw, "ingested_at": "2026-07-18T01:02:05+00:00"}
    assert await huginn.ingest(repeated) is None
    assert len(bus.messages_on("object.event")) == 1


@pytest.mark.parametrize("field", ["source", "resource_ref", "occurred_at", "payload"])
async def test_source_content_and_time_changes_still_collide_in_the_same_process(field):
    store = InMemoryStateStore()
    huginn = Huginn(bus=InMemoryBus(load_pantheon()), state_store=store)
    raw = {**_canonical_event(), "ingested_at": "2026-07-18T01:02:04+00:00"}
    await huginn.ingest(raw)
    changed = deepcopy(raw)
    changed[field] = (
        {"severity": "high"}
        if field == "payload"
        else "2026-07-18T01:02:05+00:00"
        if field == "occurred_at"
        else "different"
    )
    with pytest.raises(ValueError, match="collides"):
        await huginn.ingest(changed)


async def test_pending_retry_preserves_original_normalization_after_new_receipt_time():
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon(), isolate_handlers=False)
    failed = False

    async def interrupt_once(_topic, _payload):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("interrupted")

    bus.subscribe("object.event", "interrupt", interrupt_once)
    now = [datetime(2026, 9, 20, tzinfo=UTC)]
    raw = {**_canonical_event(), "ingested_at": "2026-07-18T01:02:04+00:00"}
    first = Huginn(bus=bus, state_store=store, clock=lambda: now[0], dedup_clock=lambda: now[0])
    with pytest.raises(RuntimeError, match="interrupted"):
        await first.ingest(raw)
    now[0] += timedelta(minutes=2)
    restarted = Huginn(bus=bus, state_store=store, clock=lambda: now[0], dedup_clock=lambda: now[0])
    recovered = await restarted.ingest({**raw, "ingested_at": "2026-07-18T01:02:05+00:00"})
    assert recovered is not None
    assert recovered["ingested_at"] == (now[0] - timedelta(minutes=2)).isoformat()
    assert recovered["occurred_at"] == raw["occurred_at"]


async def test_legacy_completed_digest_requires_exact_original_request_before_upgrade():
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon())
    raw = {**_canonical_event(), "ingested_at": "2026-07-18T01:02:04+00:00"}
    key = _terminal_key(raw["idempotency_key"])
    await store.write_state(
        key,
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "published",
            "idempotency_key": raw["idempotency_key"],
            "request_digest": request_digest(raw, include_ingested_at=True),
        },
    )
    restarted = Huginn(bus=bus, state_store=store)
    changed_receipt = {**raw, "ingested_at": "2026-07-18T01:02:05+00:00"}
    with pytest.raises(ValueError, match="collides"):
        await restarted.ingest(changed_receipt)
    assert (await store.read_state(key))["revision"] == 1
    assert await restarted.ingest(raw) is None
    retained = await store.read_state(key)
    assert retained["request_digest"] == request_digest(raw)
    assert retained["revision"] == 2
    assert await restarted.ingest(changed_receipt) is None
    assert bus.messages_on("object.event") == []


async def test_legacy_pending_claim_upgrades_only_after_exact_request_proof():
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon(), isolate_handlers=False)
    failed = False

    async def interrupt_once(_topic, _payload):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("interrupted")

    bus.subscribe("object.event", "interrupt", interrupt_once)
    now = [datetime(2026, 9, 20, tzinfo=UTC)]
    raw = {**_canonical_event(), "ingested_at": "2026-07-18T01:02:04+00:00"}
    first = Huginn(bus=bus, state_store=store, clock=lambda: now[0], dedup_clock=lambda: now[0])
    with pytest.raises(RuntimeError, match="interrupted"):
        await first.ingest(raw)
    journal = first._dedup_journal
    assert journal is not None
    shard_key = journal._shard_key(journal._shard_index(raw["idempotency_key"]))
    shard = dict(await store.read_state(shard_key))
    shard["entries"][raw["idempotency_key"]]["request_digest"] = request_digest(
        raw, include_ingested_at=True
    )
    await store.write_state(shard_key, shard)
    now[0] += timedelta(minutes=2)
    restarted = Huginn(bus=bus, state_store=store, clock=lambda: now[0], dedup_clock=lambda: now[0])
    with pytest.raises(ValueError, match="collides"):
        await restarted.ingest({**raw, "ingested_at": "2026-07-18T01:02:05+00:00"})
    recovered = await restarted.ingest(raw)
    assert recovered is not None
    assert recovered["ingested_at"] == (now[0] - timedelta(minutes=2)).isoformat()
    assert await restarted.ingest({**raw, "ingested_at": "2026-07-18T01:02:05+00:00"}) is None
    assert len(bus.messages_on("object.change")) == 1
