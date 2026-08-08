"""InMemoryBus (pantheon test bus) parity with the production bridge.

These pin the behaviours a test could otherwise silently diverge on from
the Kafka-backed :class:`EventBusBridge`: envelope enrichment, partition
keying, and per-subscriber failure isolation.
"""

from __future__ import annotations

import asyncio

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import PantheonRegistryError, load_pantheon


def _bus(**kwargs: object) -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), **kwargs)  # type: ignore[arg-type]


def test_inmemory_bus_injects_producer_principal_and_schema_version() -> None:
    bus = _bus()
    asyncio.run(bus.publish("Forseti", "object.verdict", {"correlation_id": "c"}))
    msg = bus.messages_on("object.verdict")[0]
    assert msg.payload["producer_principal"] == "Forseti"
    assert msg.payload["schema_version"] == 1
    assert msg.payload["envelope_schema_version"] == 1
    # Caller-supplied envelope authority cannot impersonate another agent.
    asyncio.run(
        bus.publish(
            "Forseti",
            "object.verdict",
            {
                "correlation_id": "d",
                "producer_principal": "Bragi",
                "schema_version": 999,
            },
        )
    )
    forged = bus.messages_on("object.verdict")[1]
    assert forged.payload["producer_principal"] == "Forseti"
    assert forged.payload["schema_version"] == 999
    assert forged.payload["envelope_schema_version"] == 1


def test_inmemory_bus_computes_partition_key() -> None:
    bus = _bus()
    asyncio.run(
        bus.publish(
            "Thor",
            "object.action-run",
            {"correlation_id": "c", "resource_id": "vm-1", "idempotency_key": "k"},
        )
    )
    assert bus.messages_on("object.action-run")[0].key == "vm-1"


def test_inmemory_bus_counts_empty_partition_key() -> None:
    bus = _bus()
    # object.verdict keys on correlation_id; absent -> empty key.
    asyncio.run(bus.publish("Forseti", "object.verdict", {"risk_verdict": "auto"}))
    assert bus.empty_partition_keys == 1


def test_inmemory_bus_rejects_wrong_owner() -> None:
    bus = _bus()
    with pytest.raises(PantheonRegistryError, match="not the owner"):
        asyncio.run(bus.publish("Bragi", "object.verdict", {"correlation_id": "c"}))


def test_inmemory_bus_isolates_raising_subscriber_by_default() -> None:
    """A raising subscriber MUST NOT stop its siblings or the publisher -
    mirroring the bridge routing a poison record to the DLQ."""
    bus = _bus()
    seen: list[str] = []

    async def boom(_t: str, _p: dict) -> None:
        raise RuntimeError("kaboom")

    async def good(_t: str, _p: dict) -> None:
        seen.append("good")

    bus.subscribe("object.event", "Heimdall", boom)
    bus.subscribe("object.event", "Forseti", good)
    asyncio.run(bus.publish("Huginn", "object.event", {"correlation_id": "c"}))

    assert seen == ["good"]  # sibling still ran
    assert bus.handler_errors == 1
    assert len(bus.dead_letters) == 1
    assert bus.dead_letters[0].principal == "Heimdall"


def test_inmemory_bus_strict_mode_propagates_handler_error() -> None:
    bus = _bus(isolate_handlers=False)

    async def boom(_t: str, _p: dict) -> None:
        raise RuntimeError("kaboom")

    bus.subscribe("object.event", "Heimdall", boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        asyncio.run(bus.publish("Huginn", "object.event", {"correlation_id": "c"}))
    assert bus.handler_errors == 1


def test_inmemory_bus_clear_history_resets_counters() -> None:
    bus = _bus()
    asyncio.run(bus.publish("Forseti", "object.verdict", {"risk_verdict": "auto"}))
    assert bus.empty_partition_keys == 1
    bus.clear_history()
    assert bus.published == []
    assert bus.dead_letters == []
    assert bus.empty_partition_keys == 0
    assert bus.handler_errors == 0


def test_inmemory_bus_skips_duplicate_subscription() -> None:
    bus = _bus()
    seen: list[str] = []

    async def handler(_t: str, _p: dict) -> None:
        seen.append("x")

    bus.subscribe("object.event", "Heimdall", handler)
    bus.subscribe("object.event", "Heimdall", handler)  # duplicate -> skipped
    asyncio.run(bus.publish("Huginn", "object.event", {"correlation_id": "c"}))
    assert seen == ["x"]  # delivered once, not twice


def test_inmemory_bus_rejects_unknown_object_topic() -> None:
    bus = _bus()

    async def handler(_t: str, _p: dict) -> None:
        return None

    with pytest.raises(ValueError, match="unknown pantheon object topic"):
        bus.subscribe("object.does-not-exist", "Heimdall", handler)


def test_inmemory_bus_handler_timeout_is_isolated() -> None:
    """A stuck handler is bounded by handler_timeout and captured, not left
    to hang the publisher forever."""
    bus = _bus(handler_timeout=0.01)

    async def stuck(_t: str, _p: dict) -> None:
        await asyncio.sleep(10)

    bus.subscribe("object.event", "Heimdall", stuck)
    asyncio.run(bus.publish("Huginn", "object.event", {"correlation_id": "c"}))
    assert bus.handler_errors == 1
    assert len(bus.dead_letters) == 1
