"""Cost sample broker publication tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.delivery.cost_sample_publisher import EventBusCostSamplePublisher
from fdai.shared.providers.cost_governance import CostObservation
from fdai.shared.providers.testing import InMemoryEventBus


@pytest.mark.asyncio
async def test_publisher_preserves_observed_time_inside_canonical_attributes() -> None:
    observed_at = datetime(2026, 8, 31, tzinfo=UTC)
    observation = CostObservation(
        observation_id=f"costobs:{'a' * 64}",
        package_id="cost-governance",
        scope_id="subscriptions/example",
        service_id="Compute",
        amount=Decimal("12"),
        currency="USD",
        event_start_at=observed_at - timedelta(days=1),
        event_end_at=observed_at,
        observed_at=observed_at,
        recorded_at=observed_at,
        source_authority="azure-consumption-usage-details",
        source_uri="cost-service:example",
        completeness=Decimal("1"),
        ontology_release_id="ontology:test",
        ontology_release_digest=f"sha256:{'b' * 64}",
        evidence_digest=f"sha256:{'c' * 64}",
        retention_until=observed_at + timedelta(days=30),
    )
    bus = InMemoryEventBus()

    await EventBusCostSamplePublisher(bus=bus, topic="fdai.events").publish_cost_sample(
        observation,
        activation_revision=2,
    )
    events = [event async for event in bus.subscribe("fdai.events", "test")]

    assert events[0].payload["attributes"]["observed_at"] == observed_at.isoformat()

    with pytest.raises(ValueError, match="USD"):
        await EventBusCostSamplePublisher(
            bus=bus,
            topic="fdai.events",
        ).publish_cost_sample(
            replace(observation, currency="EUR"),
            activation_revision=2,
        )


async def test_publish_cost_sample_preserves_evidence_identity() -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    observation = CostObservation(
        observation_id="observation-1",
        package_id="cost-governance",
        scope_id="scope-1",
        service_id="service-1",
        amount=Decimal("12.5"),
        currency="USD",
        event_start_at=now - timedelta(hours=2),
        event_end_at=now - timedelta(hours=1),
        observed_at=now,
        recorded_at=now,
        source_authority="cost-provider",
        source_uri="resource-1",
        completeness=Decimal("1"),
        ontology_release_id="ontology-1",
        ontology_release_digest=f"sha256:{'a' * 64}",
        evidence_digest=f"sha256:{'b' * 64}",
        retention_until=now + timedelta(days=30),
    )
    bus = InMemoryEventBus()
    publisher = EventBusCostSamplePublisher(bus=bus, topic="cost.samples")

    await publisher.publish_cost_sample(observation, activation_revision=7)

    events = [event async for event in bus.subscribe("cost.samples", "Huginn")]
    assert len(events) == 1
    assert events[0].key == "scope-1"
    assert events[0].payload["event_id"] == "observation-1"
    assert events[0].payload["resource_id"] == "resource-1"
    assert events[0].payload["attributes"] == {
        "scope": "scope-1",
        "resource_id": "resource-1",
        "amount_usd": 12.5,
        "source_authority": "cost-provider",
        "completeness": 1.0,
        "ontology_release_digest": f"sha256:{'a' * 64}",
        "activation_revision": 7,
        "observed_at": now.isoformat(),
    }
