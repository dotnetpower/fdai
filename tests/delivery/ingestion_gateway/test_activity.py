"""Tests for durable document lifecycle activity delivery."""

from __future__ import annotations

from fdai.delivery.ingestion_gateway.activity import (
    DurableDocumentActivitySink,
    PantheonDocumentActivitySink,
)
from fdai.delivery.ingestion_gateway.pantheon_events import EventBusDocumentIngestionIntake
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_activity_uses_fixed_topic_and_preserves_event_type() -> None:
    state = InMemoryStateStore()
    bus = InMemoryEventBus()
    sink = DurableDocumentActivitySink(
        state_store=state,
        event_bus=bus,
        event_topic="aw.document.events",
    )

    await sink.audit({"action": "document.ready", "document_id": "doc-1"})
    await sink.publish("document.ready", "doc-1", {"document_id": "doc-1"})

    records = [record async for record in bus.subscribe("aw.document.events", "test")]
    assert records[0].payload["event_type"] == "document.ready"
    assert len(state.audit_entries) == 1


def test_activity_rejects_empty_event_topic() -> None:
    try:
        DurableDocumentActivitySink(
            state_store=InMemoryStateStore(),
            event_bus=InMemoryEventBus(),
            event_topic="",
        )
    except ValueError as exc:
        assert "event_topic" in str(exc)
    else:
        raise AssertionError("empty event topic was accepted")


def _pantheon_sink() -> tuple[PantheonDocumentActivitySink, InMemoryStateStore, InMemoryEventBus]:
    state = InMemoryStateStore()
    worker_bus = InMemoryEventBus()
    pantheon_bus = InMemoryEventBus()
    sink = PantheonDocumentActivitySink(
        inner=DurableDocumentActivitySink(
            state_store=state,
            event_bus=worker_bus,
            event_topic="aw.document.events",
        ),
        ingress=EventBusDocumentIngestionIntake(bus=pantheon_bus),
    )
    return sink, state, pantheon_bus


async def test_pantheon_sink_promotes_ingress_to_huginn_event() -> None:
    sink, state, pantheon_bus = _pantheon_sink()

    await sink.audit({"action": "document.received", "document_id": "doc-1"})
    await sink.publish("document.received", "doc-1", {"state": "received"})

    events = [envelope async for envelope in pantheon_bus.subscribe("object.event", "test")]
    assert len(events) == 1
    assert events[0].payload["producer_principal"] == "Huginn"
    assert events[0].payload["action"] == "document.received"
    assert events[0].key == "doc-1"
    # The inner durable audit trail is still written.
    assert len(state.audit_entries) == 1


async def test_pantheon_sink_does_not_promote_non_ingress_actions() -> None:
    sink, _state, pantheon_bus = _pantheon_sink()

    await sink.publish("document.ready", "doc-1", {"state": "ready"})
    await sink.publish("document.held", "doc-2", {"state": "held"})

    events = [envelope async for envelope in pantheon_bus.subscribe("object.event", "test")]
    assert events == []
