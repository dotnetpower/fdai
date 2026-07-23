"""Tests for the Huginn ingress intake on the pantheon object bus."""

from __future__ import annotations

import pytest

from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.delivery.ingestion_gateway.pantheon_events import EventBusDocumentIngestionIntake
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


async def test_intake_publishes_huginn_owned_object_event() -> None:
    bus = InMemoryEventBus()
    intake = EventBusDocumentIngestionIntake(bus=bus)
    iterator = bus.subscribe("object.event", "test-consumer")

    await intake.submit(
        action="document.received",
        document_id="doc-1",
        record={"state": "received", "collection_id": "col-1"},
    )
    envelope = await anext(iterator)

    assert envelope.topic == "object.event"
    assert envelope.key == "doc-1"
    assert envelope.payload["producer_principal"] == "Huginn"
    assert envelope.payload["kind"] == "document_ingestion"
    assert envelope.payload["action"] == "document.received"
    assert envelope.payload["document_id"] == "doc-1"
    assert envelope.payload["record"]["collection_id"] == "col-1"


async def test_intake_round_trips_through_shared_pantheon_topic() -> None:
    physical_bus = InMemoryEventBus()
    object_bus = MultiplexedEventBus(
        bus=physical_bus,
        logical_topics=frozenset({"object.event"}),
        physical_topic="aw.pantheon.objects",
    )
    intake = EventBusDocumentIngestionIntake(bus=object_bus)
    iterator = object_bus.subscribe("object.event", "huginn")

    await intake.submit(
        action="document.received",
        document_id="doc-2",
        record={"state": "received"},
    )
    envelope = await anext(iterator)

    assert envelope.topic == "object.event"
    assert envelope.payload["document_id"] == "doc-2"


def test_intake_rejects_non_event_topic() -> None:
    with pytest.raises(ValueError, match="object.event"):
        EventBusDocumentIngestionIntake(bus=InMemoryEventBus(), topic="object.verdict")
