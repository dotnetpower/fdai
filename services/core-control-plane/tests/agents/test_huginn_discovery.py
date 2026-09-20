"""Huginn real-time discovery ownership and projection tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.huginn_dedup import (
    HuginnClaimInProgressError,
    request_digest,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.huginn import Huginn
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _canonical_event() -> dict[str, Any]:
    return {
        "event_id": "00000000-0000-0000-0000-000000000002",
        "idempotency_key": "azure-resource-change:event-1",
        "correlation_id": "inventory:resource-1",
        "source": "azure_event_grid.resource_change",
        "event_type": "inventory.resource_changed",
        "occurred_at": "2026-07-18T01:02:03+00:00",
        "resource_ref": "resource-1",
        "payload": {
            "signal_kind": "azure.activity_log",
            "inventory_change": {
                "kind": "upsert",
                "resource": {
                    "resource_id": "resource-1",
                    "type": "compute.vm",
                    "props": {"status": "Succeeded"},
                    "provider_ref": "/subscriptions/example/resourceGroups/rg/providers/x/y/z",
                    "last_seen": "2026-07-18T01:02:03+00:00",
                },
                "links": [
                    {
                        "change_kind": "upsert",
                        "from_id": "resource-group-1",
                        "from_type": "resource-group",
                        "link_type": "contains",
                        "to_id": "resource-1",
                        "to_type": "compute.vm",
                        "props": {},
                    }
                ],
            },
        },
    }


def test_huginn_preserves_and_projects_canonical_inventory_change() -> None:
    projected: list[dict[str, Any]] = []

    async def projector(payload):  # type: ignore[no-untyped-def]
        projected.append(dict(payload))

    huginn = Huginn(discovery_projector=projector)
    normalized = asyncio.run(huginn.ingest(_canonical_event()))

    assert normalized is not None
    assert normalized["resource_id"] == "resource-1"
    assert normalized["resource_type"] == "compute.vm"
    assert normalized["incident_correlation"] == "none"
    assert normalized["inventory_change"]["kind"] == "upsert"
    assert normalized["inventory_change"]["links"][0]["props"] == {}
    assert projected == [normalized]
    assert huginn.behavior_snapshot()["discovery_projected"] == 1


def test_huginn_preserves_recorded_failure_severity() -> None:
    event = _canonical_event()
    event["event_type"] = "availability.probe_failed"
    event["incident_correlation"] = "correlate"
    event["payload"] = {"severity": "high"}

    normalized = asyncio.run(Huginn().ingest(event))

    assert normalized is not None
    assert normalized["incident_correlation"] == "correlate"
    assert normalized["severity"] == "high"


def test_projection_failure_does_not_commit_huginn_dedup() -> None:
    calls = 0

    async def fail_once(_payload):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic projector failure")

    huginn = Huginn(discovery_projector=fail_once)
    with pytest.raises(RuntimeError, match="synthetic projector failure"):
        asyncio.run(huginn.ingest(_canonical_event()))

    assert asyncio.run(huginn.ingest(_canonical_event())) is not None
    assert calls == 2
    assert huginn.behavior_snapshot()["discovery_projection_failed"] == 1


def test_discovery_dedup_eviction_allows_old_key_redelivery() -> None:
    huginn = Huginn(dedup_capacity=1)
    first = _canonical_event()
    second = _canonical_event()
    second["idempotency_key"] = "azure-resource-change:event-2"
    second["event_id"] = "00000000-0000-0000-0000-000000000003"

    assert asyncio.run(huginn.ingest(first)) is not None
    assert asyncio.run(huginn.ingest(second)) is not None
    assert asyncio.run(huginn.ingest(first)) is not None
    assert huginn.health()["dedup_size"] == 1


def test_health_exposes_unobserved_discovery_signals() -> None:
    health = Huginn().health()

    assert health["discovery"] == {
        "projection": "not_bound",
        "cursor": "not_observed",
        "backpressure": "not_observed",
        "source_health": "not_observed",
    }


async def test_durable_dedup_recovers_pending_publication_after_lease_expiry() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon(), isolate_handlers=False)
    failed = False

    async def fail_once(_topic: str, _payload: dict[str, Any]) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("synthetic publish interruption")

    bus.subscribe("object.event", "fail-once", fail_once)
    dedup_now = [datetime(2026, 9, 20, 0, 0, tzinfo=UTC)]
    ingested_at = datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
    first = Huginn(
        bus=bus,
        state_store=store,
        clock=lambda: ingested_at,
        dedup_clock=lambda: dedup_now[0],
        dedup_claim_lease=timedelta(seconds=30),
    )
    with pytest.raises(RuntimeError, match="synthetic publish interruption"):
        await first.ingest(_canonical_event())

    dedup_now[0] += timedelta(seconds=31)
    restarted = Huginn(
        bus=bus,
        state_store=store,
        clock=lambda: ingested_at + timedelta(hours=1),
        dedup_clock=lambda: dedup_now[0],
        dedup_claim_lease=timedelta(seconds=30),
    )
    recovered = await restarted.ingest(_canonical_event())

    assert recovered is not None
    assert recovered["ingested_at"] == ingested_at.isoformat()
    assert len(bus.messages_on("object.event")) == 2
    assert len(bus.messages_on("object.change")) == 1


async def test_durable_dedup_rejects_live_cross_replica_claim() -> None:
    store = InMemoryStateStore()
    bus = InMemoryBus(load_pantheon(), isolate_handlers=False)

    async def fail(_topic: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("synthetic publish interruption")

    bus.subscribe("object.event", "fail", fail)
    dedup_now = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)
    first = Huginn(bus=bus, state_store=store, dedup_clock=lambda: dedup_now)
    with pytest.raises(RuntimeError, match="synthetic publish interruption"):
        await first.ingest(_canonical_event())

    competing = Huginn(state_store=store, dedup_clock=lambda: dedup_now)
    with pytest.raises(HuginnClaimInProgressError, match="claim remains active"):
        await competing.ingest(_canonical_event())


async def test_durable_dedup_rehydrates_completed_key() -> None:
    store = InMemoryStateStore()
    first = Huginn(state_store=store)
    assert await first.ingest(_canonical_event()) is not None

    restarted = Huginn(state_store=store)
    assert await restarted.rehydrate() == 1
    assert await restarted.ingest(_canonical_event()) is None


async def test_durable_dedup_does_not_audit_mechanical_delivery_checkpoints() -> None:
    store = InMemoryStateStore()

    assert await Huginn(state_store=store).ingest(_canonical_event()) is not None

    assert tuple(store.audit_entries) == ()


async def test_durable_dedup_rejects_idempotency_payload_collision() -> None:
    store = InMemoryStateStore()
    assert await Huginn(state_store=store).ingest(_canonical_event()) is not None
    changed = _canonical_event()
    changed["resource_ref"] = "resource-2"

    with pytest.raises(ValueError, match="collides with another raw request"):
        await Huginn(state_store=store).ingest(changed)


async def test_durable_dedup_migrates_and_compacts_legacy_journal() -> None:
    store = InMemoryStateStore()
    first = _canonical_event()
    second = _canonical_event()
    second["idempotency_key"] = "azure-resource-change:event-2"
    second["event_id"] = "00000000-0000-0000-0000-000000000003"
    await store.write_state(
        "pantheon/huginn/ingress-dedup",
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "capacity": 2,
            "next_sequence": 3,
            "entries": {
                first["idempotency_key"]: {
                    "request_digest": request_digest(first),
                    "status": "published",
                    "owner_token": "",
                    "lease_expires_at": "",
                    "sequence": 1,
                    "payload": None,
                    "change_projection": None,
                },
                second["idempotency_key"]: {
                    "request_digest": request_digest(second),
                    "status": "published",
                    "owner_token": "",
                    "lease_expires_at": "",
                    "sequence": 2,
                    "payload": None,
                    "change_projection": None,
                },
            },
        },
    )
    migrated = Huginn(state_store=store, dedup_capacity=2)

    assert await migrated.rehydrate() == 2
    legacy = await store.read_state("pantheon/huginn/ingress-dedup")
    assert legacy is not None and legacy["entries"] == {}
    assert await migrated.ingest(first) is None

    third = _canonical_event()
    third["idempotency_key"] = "azure-resource-change:event-3"
    third["event_id"] = "00000000-0000-0000-0000-000000000004"
    assert await migrated.ingest(third) is not None

    restarted = Huginn(state_store=store, dedup_capacity=2)
    assert await restarted.rehydrate() == 2
    assert await restarted.ingest(first) is not None
