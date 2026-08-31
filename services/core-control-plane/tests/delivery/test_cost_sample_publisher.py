"""Coverage for broker-only cost sample publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.delivery.cost_sample_publisher import EventBusCostSamplePublisher
from fdai.shared.providers.cost_governance import CostObservation
from fdai.shared.providers.testing import InMemoryEventBus


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
    }
