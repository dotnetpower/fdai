"""Raw Event Grid to canonical Huginn ingress consumer tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.runtime.consumers import _consume_resource_changes
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_ROOT = Path(__file__).resolve().parents[2]
_VOCABULARY = _ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
_ARM_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.Compute/virtualMachines/vm-1"
)


def _registry():
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(_VOCABULARY.read_text(encoding="utf-8"))
    )


def _raw_event() -> dict[str, object]:
    return {
        "id": "00000000-0000-0000-0000-000000000002",
        "eventType": "Microsoft.Resources.ResourceWriteSuccess",
        "eventTime": "2026-07-18T01:02:03Z",
        "subject": _ARM_ID,
        "data": {"resourceUri": _ARM_ID, "status": "Succeeded"},
    }


async def test_resource_change_consumer_publishes_canonical_event() -> None:
    bus = InMemoryEventBus()
    await bus.publish("aw.inventory.raw", "raw-1", _raw_event())

    await _consume_resource_changes(
        bus=bus,
        raw_topic="aw.inventory.raw",
        canonical_topic="aw.change.events",
        resource_types=_registry(),
        stop=asyncio.Event(),
    )

    records = [item async for item in bus.subscribe("aw.change.events", "assert")]
    assert len(records) == 1
    assert records[0].payload["event_type"] == "inventory.resource_changed"
    assert records[0].payload["payload"]["inventory_change"]["kind"] == "upsert"


async def test_resource_change_consumer_dead_letters_malformed_event() -> None:
    bus = InMemoryEventBus()
    await bus.publish("aw.inventory.raw", "raw-1", {"eventType": 42})

    await _consume_resource_changes(
        bus=bus,
        raw_topic="aw.inventory.raw",
        canonical_topic="aw.change.events",
        resource_types=_registry(),
        stop=asyncio.Event(),
    )

    records = [item async for item in bus.subscribe("aw.inventory.raw.dlq", "assert")]
    assert len(records) == 1
    assert records[0].payload["reason"].startswith("resource_discovery_normalize_error")
