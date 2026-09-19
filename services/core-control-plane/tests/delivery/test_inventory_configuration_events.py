from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import PolicyResult, RuleIndex, T0Engine
from fdai.delivery.inventory_configuration_events import (
    configuration_delivery_pending,
    configuration_delivery_record,
    publish_promoted_resource_events,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.shared.contracts.models import Event, Rule
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

REPO_ROOT = Path(__file__).resolve().parents[4]


class _DenyEvaluator:
    def evaluate(self, rule: Rule, resource_props: object) -> PolicyResult:
        del rule, resource_props
        return PolicyResult(denied=True, context={"reason": "test-policy-denied"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_count", True),
        ("resource_count", -1),
        ("observation_digest", "invalid"),
        ("execution_authority", True),
        ("extra", "invalid"),
    ],
)
def test_delivery_marker_rejects_malformed_completion(field: str, value: object) -> None:
    observation = PromotedInventoryObservation(
        generation="generation-1",
        resources=(),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    marker = configuration_delivery_record(observation, completed=True)
    marker[field] = value
    with pytest.raises(ValueError, match="marker is invalid"):
        configuration_delivery_pending(marker, generation=observation.generation)


async def test_truncated_properties_cannot_publish_a_complete_event() -> None:
    bus = InMemoryEventBus()
    observation = PromotedInventoryObservation(
        generation="generation-1",
        resources=(
            ResourceRecord(
                resource_id="example",
                type="compute.vm",
                props={"_truncated": True},
            ),
        ),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="truncated inventory"):
        await publish_promoted_resource_events(
            observation, event_bus=bus, topic="events", scope_ref="example"
        )
    assert [event async for event in bus.subscribe("events", "reader")] == []


@pytest.mark.asyncio
async def test_promoted_inventory_publishes_configuration_observations() -> None:
    bus = InMemoryEventBus()
    observation = PromotedInventoryObservation(
        generation="generation-1",
        resources=(
            ResourceRecord(
                resource_id="resource-example",
                type="managed-identity",
                props={"role_assignments": []},
                last_seen="2026-09-17T00:00:00Z",
            ),
        ),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 17, tzinfo=UTC),
    )

    published = await publish_promoted_resource_events(
        observation,
        event_bus=bus,
        topic="events",
        scope_ref="scope-example",
    )

    records = [item async for item in bus.subscribe("events", "reader")]
    assert published == 1
    assert records[0].key == "resource-example"
    assert records[0].payload["event_type"] == "inventory.resource_observed"
    assert records[0].payload["resource_ref"] == "resource-example"
    assert records[0].payload["payload"]["resource"] == {
        "resource_id": "resource-example",
        "type": "managed-identity",
        "props": {"role_assignments": []},
        "provider_ref": None,
        "last_seen": "2026-09-17T00:00:00Z",
    }
    inventory_observation = records[0].payload["payload"]["inventory_observation"]
    assert inventory_observation == {
        "kind": "full",
        "properties_complete": True,
        "generation_digest": inventory_observation["generation_digest"],
        "scope_ref": "scope-example",
    }
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", inventory_observation["generation_digest"])


@pytest.mark.asyncio
async def test_promoted_inventory_event_identity_is_retry_stable() -> None:
    bus = InMemoryEventBus()
    observation = PromotedInventoryObservation(
        generation="generation-1",
        resources=(
            ResourceRecord(
                resource_id="resource-example",
                type="managed-identity",
                props={"role_assignments": []},
                last_seen="2026-09-17T00:00:00Z",
            ),
        ),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 17, tzinfo=UTC),
    )

    for _ in range(2):
        await publish_promoted_resource_events(
            observation,
            event_bus=bus,
            topic="events",
            scope_ref="scope-example",
        )

    records = [item async for item in bus.subscribe("events", "reader")]
    assert records[0].payload["event_id"] == records[1].payload["event_id"]
    assert records[0].payload["idempotency_key"] == records[1].payload["idempotency_key"]


@pytest.mark.asyncio
async def test_promoted_inventory_event_dispatches_shipped_configuration_rule() -> None:
    bus = InMemoryEventBus()
    observation = PromotedInventoryObservation(
        generation="generation-1",
        resources=(
            ResourceRecord(
                resource_id="resource-example",
                type="managed-identity",
                props={"role_assignments": []},
                last_seen="2026-09-17T00:00:00Z",
            ),
        ),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    await publish_promoted_resource_events(
        observation,
        event_bus=bus,
        topic="events",
        scope_ref="scope-example",
    )
    envelope = [item async for item in bus.subscribe("events", "reader")][0]
    event = Event.model_validate(envelope.payload)
    rule = Rule.model_validate(
        yaml.safe_load(
            (
                REPO_ROOT
                / "rule-catalog/catalog"
                / "managed-identity.role-assignment.no-privileged-subscription-scope.yaml"
            ).read_text(encoding="utf-8")
        )
    )
    signal_types = load_signal_type_registry_from_mapping(
        yaml.safe_load(
            (REPO_ROOT / "rule-catalog/vocabulary/signal-types.yaml").read_text(encoding="utf-8")
        )
    )
    engine = T0Engine(
        index=RuleIndex.build((rule,), signal_types=signal_types),
        evaluator=_DenyEvaluator(),
    )

    verdict = engine.evaluate(
        event_id=str(event.event_id),
        signal_id=str(event.event_id),
        resource_id=event.resource_ref or "",
        resource_type=str(event.payload["resource"]["type"]),
        resource_props=event.payload["resource"]["props"],
        signal_type=event.event_type,
    )

    assert verdict.matched is True
    assert verdict.findings[0].rule_id == rule.id


@pytest.mark.asyncio
async def test_incomplete_inventory_does_not_publish_configuration_observations() -> None:
    with pytest.raises(ValueError, match="complete promoted inventory"):
        await publish_promoted_resource_events(
            PromotedInventoryObservation(
                generation="generation-1",
                resources=(),
                links=(),
                complete=False,
                recorded_at=datetime(2026, 9, 17, tzinfo=UTC),
            ),
            event_bus=InMemoryEventBus(),
            topic="events",
            scope_ref="scope-example",
        )
