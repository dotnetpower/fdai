"""Huginn redrives its own admitted inventory outbox, not a reconstructed raw request."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.core.ontology_platform.operational_history_lifecycle import NoCurrentIncarnationError
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_huginn_discovery import _canonical_event


async def _project(_payload):
    return None


async def _pending(*, count=1, source_event_type="inventory.resource_changed"):
    store = InMemoryStateStore()
    now = [datetime(2026, 9, 20, tzinfo=UTC)]
    writer = Huginn(
        state_store=store,
        clock=lambda: now[0],
        dedup_clock=lambda: now[0],
        discovery_projector=_project,
    )
    for index in range(count):
        raw = _canonical_event()
        raw["idempotency_key"] = f"pending-{index}"
        raw["event_id"] = f"pending-{index}"
        raw["event_type"] = source_event_type
        await writer.ingest(raw)
    bus = InMemoryBus(load_pantheon(), isolate_handlers=False)
    reader = Huginn(
        state_store=store,
        bus=bus,
        clock=lambda: now[0],
        dedup_clock=lambda: now[0],
        discovery_projector=_project,
    )
    return store, now, bus, reader


async def test_pending_delivery_recovers_without_raw_input_and_preserves_original_time():
    store, now, bus, reader = await _pending()
    original_time = now[0].isoformat()
    before = await store.read_states("pantheon/huginn/ingress-dedup/shard-", limit=64)
    digest = next(entry["request_digest"] for row in before for entry in row["entries"].values())
    now[0] += timedelta(minutes=2)

    assert await reader.recover_pending_inventory() == 1
    assert await reader.recover_pending_inventory() == 0
    assert len(bus.messages_on("object.event")) == 1
    assert len(bus.messages_on("object.change")) == 1
    delivered = bus.messages_on("object.event")[0].payload
    assert delivered["ingested_at"] == original_time
    assert delivered["occurred_at"] == _canonical_event()["occurred_at"]
    assert delivered["incident_correlation"] == "none"
    terminal = await store.read_states("pantheon/huginn/ingress-dedup/terminal/", limit=8)
    assert len(terminal) == 1
    assert terminal[0]["request_digest"] == digest
    assert terminal[0]["status"] == "published"


async def test_recovery_holds_live_lease_and_unsupported_authority_family():
    _, now, bus, reader = await _pending()
    assert await reader.recover_pending_inventory() == 0
    assert reader.behavior_snapshot()["ingress_recovery:lease_active"] == 1
    assert bus.messages_on("object.event") == []
    _, other_now, other_bus, other_reader = await _pending(source_event_type="availability.failure")
    other_now[0] += timedelta(minutes=2)
    assert await other_reader.recover_pending_inventory() == 0
    assert other_bus.messages_on("object.event") == []


async def test_recovery_is_bounded_and_maintenance_drives_it_without_a_new_raw_event():
    _, now, bus, reader = await _pending(count=20)
    now[0] += timedelta(minutes=2)
    assert await reader.recover_pending_inventory() == 8
    await reader.maintenance_tick()
    assert len(bus.messages_on("object.event")) == 16
    assert await reader.recover_pending_inventory() == 4
    assert await reader.recover_pending_inventory() == 0


async def test_recovery_retries_retained_payload_after_actual_publication_failure():
    _, now, bus, reader = await _pending()
    now[0] += timedelta(minutes=2)
    failed = False

    async def interrupt_once(_topic, _payload):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("publication interrupted")

    bus.subscribe("object.event", "interrupt", interrupt_once)
    with pytest.raises(RuntimeError, match="publication interrupted"):
        await reader.recover_pending_inventory()
    assert await reader.recover_pending_inventory() == 1
    assert len(bus.messages_on("object.change")) == 1


async def test_recovery_never_marks_completion_without_projection_binding():
    store, now, bus, _ = await _pending()
    now[0] += timedelta(minutes=2)
    reader = Huginn(
        state_store=store,
        bus=bus,
        clock=lambda: now[0],
        dedup_clock=lambda: now[0],
    )
    assert await reader.recover_pending_inventory() == 0
    assert reader.behavior_snapshot()["ingress_recovery:unbound"] == 1
    assert bus.messages_on("object.event") == []
    assert await store.read_states("pantheon/huginn/ingress-dedup/terminal/", limit=8) == ()


async def test_recovery_rejects_retained_inventory_with_authority_drift():
    store, now, bus, reader = await _pending()
    now[0] += timedelta(minutes=2)
    journal = reader._dedup_journal
    assert journal is not None
    key = journal._shard_key(journal._shard_index("pending-0"))
    state = dict(await store.read_state(key))
    state["entries"]["pending-0"]["payload"]["incident_correlation"] = "correlate"
    await store.write_state(key, state)
    with pytest.raises(ValueError, match="invalid ownership or authority"):
        await reader.recover_pending_inventory()
    assert bus.messages_on("object.event") == []
    assert await store.read_states("pantheon/huginn/ingress-dedup/terminal/", limit=8) == ()


async def test_one_failing_claim_does_not_block_the_other_pending_claims():
    store, now, bus, _ = await _pending(count=3)
    now[0] += timedelta(minutes=2)

    async def project_except_first(payload):
        if payload.get("event_id") == "pending-0":
            raise NoCurrentIncarnationError(
                "sparse or tombstone observation has no current incarnation"
            )

    reader = Huginn(
        state_store=store,
        bus=bus,
        clock=lambda: now[0],
        dedup_clock=lambda: now[0],
        discovery_projector=project_except_first,
    )
    with pytest.raises(NoCurrentIncarnationError, match="no current incarnation"):
        await reader.recover_pending_inventory()
    assert len(bus.messages_on("object.event")) == 2
    assert reader.behavior_snapshot()["ingress_recovery:claim_failed"] == 1
    assert reader.behavior_snapshot()["ingress_recovery:completed"] == 2
