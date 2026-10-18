from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.cost_optimization_publisher import (
    EventBusCostOptimizationCandidatePublisher,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _candidate() -> dict[str, object]:
    return {
        "kind": "cross_vertical_candidate",
        "correlation_id": "optimization-example",
        "idempotency_key": "optimization-example:v1",
        "resource_id": "optimization-set-example",
        "observed_at": NOW.isoformat(),
        "action_type": "remediate.right-size",
        "effects": [
            {
                "objective_id": "objective.cost",
                "utility": 0.7,
                "confidence": 0.9,
                "metric": "monthly_cost_usd",
                "expected_min": 100.0,
                "expected_max": 120.0,
                "observation_window_seconds": 86400,
            }
        ],
        "evidence_refs": ["cost-optimization:test"],
        "source_freshness": [
            {
                "source": "cost-analytics",
                "observed_at": NOW.isoformat(),
                "max_age_seconds": 7200,
            }
        ],
    }


async def test_publisher_uses_canonical_event_ingress_without_agent_principal() -> None:
    bus = InMemoryEventBus()
    publisher = EventBusCostOptimizationCandidatePublisher(bus, "raw-events")

    await publisher.publish_cost_optimization_candidate(
        _candidate(),
        activation_revision=7,
    )

    records = [item async for item in bus.subscribe("raw-events", "test")]
    assert len(records) == 1
    payload = records[0].payload
    assert payload["event_type"] == "specialist.cost_optimization_candidate"
    assert payload["resource_id"] == "optimization-set-example"
    assert payload["attributes"]["activation_revision"] == 7
    assert "producer_principal" not in payload["attributes"]["candidate"]


async def test_publisher_rejects_spoofed_owner_and_invalid_candidate() -> None:
    publisher = EventBusCostOptimizationCandidatePublisher(InMemoryEventBus(), "raw-events")

    with pytest.raises(ValueError, match="MUST NOT supply an agent principal"):
        await publisher.publish_cost_optimization_candidate(
            {**_candidate(), "producer_principal": "Njord"},
            activation_revision=7,
        )
    with pytest.raises(ValueError, match="effects"):
        await publisher.publish_cost_optimization_candidate(
            {**_candidate(), "effects": []},
            activation_revision=7,
        )
