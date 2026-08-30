from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fdai.agents import PantheonRuntime
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.freyr import Freyr
from fdai.agents.thor import Thor
from fdai.core.capacity import CapacityGraduationController
from fdai.rule_catalog.schema.capacity_graduation_policy import (
    load_capacity_graduation_policy,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 8, 30, 3, tzinfo=UTC)


def _controller() -> CapacityGraduationController:
    return CapacityGraduationController(
        load_capacity_graduation_policy(
            REPO_ROOT / "rule-catalog" / "capacity-graduation-policy.yaml"
        )
    )


async def test_capacity_graduation_stays_shadow_through_forseti_and_thor() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    controller = _controller()
    freyr = Freyr(bus=bus, graduation_controller=controller, clock=lambda: NOW)
    forseti = Forseti(bus=bus)
    thor = Thor(bus=bus)
    bus.subscribe("object.event", "Freyr", freyr.on_typed_message)
    bus.subscribe("object.cost-anomaly", "Freyr", freyr.on_typed_message)
    bus.subscribe(
        "object.capacity-graduation-recommendation",
        "Forseti",
        forseti.on_typed_message,
    )
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)

    await bus.publish(
        "Njord",
        "object.cost-anomaly",
        {
            "producer_principal": "Njord",
            "correlation_id": "graduation:one",
            "idempotency_key": "cost:one",
            "resource_id": "resource:example",
            "evidence_ref": "evidence:cost",
            "observed_at": NOW.isoformat(),
        },
    )
    await bus.publish(
        "Huginn",
        "object.event",
        {
            "producer_principal": "Huginn",
            "correlation_id": "graduation:one",
            "idempotency_key": "capacity:one",
            "event_id": "event:capacity:one",
            "event_type": "specialist.capacity_graduation_evidence",
            "detected_at": NOW.isoformat(),
            "resource_id": "resource:example",
            "attributes": {
                "transition": "aks_or_cell",
                "target_ref": "resource:example",
                "source_authority_ref": "measurement:capacity",
                "evidence_refs": ["evidence:capacity"],
                "complete": True,
                "synthetic": False,
                "projected_cost_ratio": 1.1,
                "required_capabilities": ["gpu"],
            },
        },
    )

    recommendation = bus.messages_on("object.capacity-graduation-recommendation")
    verdicts = bus.messages_on("object.verdict")
    assert len(recommendation) == 1
    assert recommendation[0].payload["status"] == "recommend"
    assert recommendation[0].payload["shadow_only"] is True
    assert recommendation[0].payload["execution_authority"] is False
    assert verdicts[-1].payload["kind"] == "capacity_graduation"
    assert verdicts[-1].payload["risk_verdict"] == "shadow"
    assert bus.messages_on("object.action-run") == []
    assert thor.behavior_snapshot()["capacity_graduation_verdict_ignored"] == 1


async def test_capacity_graduation_holds_without_njord_cost_evidence() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    controller = _controller()
    freyr = Freyr(bus=bus, graduation_controller=controller, clock=lambda: NOW)

    await freyr.on_typed_message(
        "object.event",
        {
            "producer_principal": "Huginn",
            "correlation_id": "graduation:missing-cost",
            "idempotency_key": "capacity:missing-cost",
            "event_id": "event:capacity:missing-cost",
            "event_type": "specialist.capacity_graduation_evidence",
            "detected_at": NOW.isoformat(),
            "resource_id": "resource:example",
            "attributes": {
                "transition": "dedicated_vector_store",
                "target_ref": "resource:example",
                "source_authority_ref": "measurement:capacity",
                "evidence_refs": ["evidence:capacity"],
                "complete": True,
                "synthetic": False,
                "projected_cost_ratio": 1.0,
                "capacity_ratio": 0.8,
            },
        },
    )

    recommendation = bus.messages_on("object.capacity-graduation-recommendation")
    assert len(recommendation) == 1
    assert recommendation[0].payload["status"] == "hold"
    assert recommendation[0].payload["reason_codes"] == ["cost_evidence_missing"]


def test_pantheon_runtime_injects_the_reviewed_graduation_controller() -> None:
    controller = _controller()

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
        capacity_graduation_controller=controller,
    )

    freyr = cast(Freyr, runtime.agents["Freyr"])
    assert freyr._graduation_controller is controller  # noqa: SLF001
