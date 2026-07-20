"""Huginn real-time discovery ownership and projection tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fdai.agents.huginn import Huginn


def _canonical_event() -> dict[str, Any]:
    return {
        "event_id": "00000000-0000-0000-0000-000000000002",
        "idempotency_key": "azure-resource-change:event-1",
        "correlation_id": "inventory:resource-1",
        "source": "azure_event_grid.resource_change",
        "event_type": "inventory.resource_changed",
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
