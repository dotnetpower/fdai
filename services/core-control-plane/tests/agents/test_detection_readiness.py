from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.muninn import Muninn
from fdai.agents.saga import Saga
from fdai.core.readiness import (
    DETECTION_READINESS_STATE_PREFIX,
    DetectionReadinessDimension,
    detection_readiness_state_key,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)


def _raw_observation(dimension: DetectionReadinessDimension, index: int) -> dict[str, Any]:
    return {
        "id": f"readiness-{index}",
        "correlation_id": "readiness-cluster-example",
        "resource_id": "cluster/example",
        "resource_type": "kubernetes-cluster",
        "event_type": "detection.readiness.observed",
        "attributes": {
            "dimension": dimension.value,
            "status": "passed",
            "observed_at": (_NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (_NOW + timedelta(minutes=4)).isoformat(),
            "source": "azure.monitor",
            "evidence_digest": f"{index + 1:064x}",
            "pass_id": "a" * 64,
        },
    }


def test_huginn_to_heimdall_reduces_readiness_in_shadow() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)

    for index, dimension in enumerate(DetectionReadinessDimension):
        asyncio.run(huginn.ingest(_raw_observation(dimension, index)))

    drifts = bus.messages_on("object.drift")
    assert len(drifts) == 1
    assert drifts[-1].principal == "Heimdall"
    assert drifts[-1].payload["decision"] == "ready"
    assert drifts[-1].payload["authority_ceiling"] == "shadow"
    assert drifts[-1].payload["missing_dimensions"] == []
    assert len(drifts[-1].payload["observations"]) == len(DetectionReadinessDimension)


def test_malformed_observation_never_publishes_false_readiness() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)

    asyncio.run(
        heimdall.on_typed_message(
            "object.event",
            {
                "resource_id": "cluster/example",
                "event_type": "detection.readiness.observed",
                "attributes": {"status": "passed"},
            },
        )
    )

    assert bus.messages_on("object.drift") == []
    assert heimdall.behavior_snapshot()["detection_readiness:invalid"] == 1


def test_replayed_raw_observation_is_deduplicated_by_huginn() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    raw = _raw_observation(DetectionReadinessDimension.DISCOVERED, 0)

    asyncio.run(huginn.ingest(raw))
    asyncio.run(huginn.ingest(raw))

    assert bus.messages_on("object.drift") == []


def test_incomplete_new_pass_does_not_replace_completed_snapshot() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    for index, dimension in enumerate(DetectionReadinessDimension):
        asyncio.run(huginn.ingest(_raw_observation(dimension, index)))
    first = bus.messages_on("object.drift")[-1].payload
    next_pass = _raw_observation(DetectionReadinessDimension.DISCOVERED, 99)
    next_pass["attributes"]["pass_id"] = "b" * 64

    asyncio.run(huginn.ingest(next_pass))

    assert len(bus.messages_on("object.drift")) == 1
    assert bus.messages_on("object.drift")[-1].payload == first


def test_overlapping_pass_does_not_discard_earlier_partial_collection() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    dimensions = tuple(DetectionReadinessDimension)
    for index, dimension in enumerate(dimensions[:-1]):
        asyncio.run(huginn.ingest(_raw_observation(dimension, index)))
    overlapping = _raw_observation(DetectionReadinessDimension.DISCOVERED, 99)
    overlapping["attributes"]["pass_id"] = "b" * 64
    asyncio.run(huginn.ingest(overlapping))

    asyncio.run(huginn.ingest(_raw_observation(dimensions[-1], len(dimensions) - 1)))

    drifts = bus.messages_on("object.drift")
    assert len(drifts) == 1
    assert drifts[0].payload["decision"] == "ready"


def test_muninn_persists_snapshot_and_saga_audits_transition() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    durable = InMemoryStateStore()
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    muninn = Muninn(durable_state_store=durable)
    saga = Saga()
    huginn = Huginn(bus=bus)
    for agent in (muninn, saga):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.drift", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.state-snapshot", "Saga", saga.on_typed_message)

    for index, dimension in enumerate(DetectionReadinessDimension):
        asyncio.run(huginn.ingest(_raw_observation(dimension, index)))

    stored = asyncio.run(durable.read_states(DETECTION_READINESS_STATE_PREFIX, limit=10))
    snapshots = bus.messages_on("object.state-snapshot")
    assert len(stored) == 1
    assert stored[0]["decision"] == "ready"
    assert stored[0]["authority_ceiling"] == "shadow"
    assert snapshots[-1].principal == "Muninn"
    assert saga.audit_chain.entries[-1].topic == "object.state-snapshot"


def test_muninn_deduplicates_same_readiness_snapshot() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    muninn = Muninn()
    muninn.bind_bus(bus)
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    for index, dimension in enumerate(DetectionReadinessDimension):
        asyncio.run(huginn.ingest(_raw_observation(dimension, index)))
    drift = bus.messages_on("object.drift")[0].payload

    asyncio.run(muninn.on_typed_message("object.drift", drift))
    asyncio.run(muninn.on_typed_message("object.drift", drift))

    assert len(bus.messages_on("object.state-snapshot")) == 1
    assert muninn.behavior_snapshot()["detection_readiness:duplicate"] == 1


def test_muninn_rejects_older_readiness_snapshot_delivered_late() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    durable = InMemoryStateStore()
    muninn = Muninn(durable_state_store=durable)
    muninn.bind_bus(bus)
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    for index, dimension in enumerate(DetectionReadinessDimension):
        asyncio.run(huginn.ingest(_raw_observation(dimension, index)))
    older = bus.messages_on("object.drift")[0].payload
    newer = {
        **older,
        "generated_at": (_NOW + timedelta(minutes=1)).isoformat(),
        "idempotency_key": "detection-readiness:newer",
    }

    asyncio.run(muninn.on_typed_message("object.drift", newer))
    restarted = Muninn(durable_state_store=durable)
    restarted.bind_bus(bus)
    asyncio.run(restarted.on_typed_message("object.drift", older))

    stored = asyncio.run(durable.read_state(detection_readiness_state_key("cluster/example")))
    assert stored is not None
    assert stored["idempotency_key"] == "detection-readiness:newer"
    assert len(bus.messages_on("object.state-snapshot")) == 1
    assert restarted.behavior_snapshot()["detection_readiness:stale"] == 1


def test_forseti_records_readiness_without_creating_a_verdict() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti(bus=bus)

    asyncio.run(
        forseti.on_typed_message(
            "object.drift",
            {
                "kind": "detection_readiness",
                "resource_id": "cluster/example",
                "decision": "partial",
                "authority_ceiling": "shadow",
            },
        )
    )

    assert bus.messages_on("object.verdict") == []
    assert forseti.behavior_snapshot()["detection_readiness:partial"] == 1


def test_raw_readiness_observation_fans_out_without_creating_hil() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti(bus=bus)
    heimdall = Heimdall(bus=bus, forecast_clock=lambda: _NOW)
    huginn = Huginn(bus=bus)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)

    asyncio.run(huginn.ingest(_raw_observation(DetectionReadinessDimension.DISCOVERED, 0)))

    assert bus.messages_on("object.verdict") == []
    assert bus.messages_on("object.drift") == []
    assert forseti.behavior_snapshot()["detection_readiness:observation_deferred"] == 1


def test_forseti_demotes_auto_event_under_readiness_ceiling() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti(bus=bus)
    asyncio.run(
        forseti.on_typed_message(
            "object.drift",
            {
                "kind": "detection_readiness",
                "resource_id": "cluster/example",
                "decision": "ready",
                "authority_ceiling": "shadow",
            },
        )
    )

    asyncio.run(
        forseti.on_typed_message(
            "object.event",
            {
                "event_type": "restart_needed",
                "resource_id": "cluster/example",
                "correlation_id": "pod-failure-1",
            },
        )
    )

    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "detection_readiness_ceiling"
    assert verdict["detection_readiness"] == {
        "decision": "ready",
        "authority_ceiling": "shadow",
    }
