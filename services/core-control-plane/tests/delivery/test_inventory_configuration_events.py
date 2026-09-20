from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import PolicyResult, RuleIndex, T0Engine
from fdai.delivery.inventory_configuration_events import (
    INVENTORY_CONFIGURATION_DELIVERY_KEY,
    complete_configuration_delivery,
    configuration_delivery_key,
    configuration_delivery_pending,
    configuration_delivery_record,
    configuration_projection_record,
    prepare_configuration_delivery,
    publish_promoted_resource_events,
    retained_configuration_delivery,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.persistence.postgres_inventory_delivery import verified_delivery_observation
from fdai.rule_catalog.schema.signal_type import load_signal_type_registry_from_mapping
from fdai.shared.contracts.models import Event, Rule
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]


class _DenyEvaluator:
    def evaluate(self, rule: Rule, resource_props: object) -> PolicyResult:
        del rule, resource_props
        return PolicyResult(denied=True, context={"reason": "test-policy-denied"})


async def test_delivery_generations_preserve_pending_and_completed_identity() -> None:
    store = InMemoryStateStore()
    first = PromotedInventoryObservation(
        generation="generation-1",
        resources=(),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    second = replace(first, generation="generation-2")
    await prepare_configuration_delivery(store, first)
    await prepare_configuration_delivery(store, second)
    assert await store.read_state(configuration_delivery_key(first.generation)) == (
        configuration_delivery_record(first)
    )
    await complete_configuration_delivery(store, first)
    assert await store.read_state(INVENTORY_CONFIGURATION_DELIVERY_KEY) == (
        configuration_delivery_record(second)
    )
    await prepare_configuration_delivery(store, first)
    assert await retained_configuration_delivery(store, first) == (
        configuration_delivery_record(first, completed=True)
    )
    with pytest.raises(ValueError, match="content changed"):
        await prepare_configuration_delivery(
            store,
            replace(first, resources=(ResourceRecord(resource_id="changed", type="compute.vm"),)),
        )


@pytest.mark.parametrize(
    "defect",
    [None, "key", "resource", "publication", "missing_snapshot", "authority", "recorded_at"],
)
def test_recovery_requires_exact_committed_generation(defect: str | None) -> None:
    observation = PromotedInventoryObservation(
        generation="older-generation",
        resources=(),
        links=(),
        complete=True,
        recorded_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    pending = configuration_delivery_record(observation)
    publication = configuration_projection_record(
        observation,
        ontology_release_digest="sha256:" + "a" * 64,
        manifest_digest="sha256:" + "b" * 64,
    )
    key = configuration_delivery_key(observation.generation)
    if defect == "key":
        key = configuration_delivery_key("other-generation")
    if defect == "publication":
        publication["observation_digest"] = "sha256:" + "c" * 64
    if defect == "authority":
        publication["execution_authority"] = 0
    if defect == "recorded_at":
        publication["recorded_at"] = "2026-09-19T00:00:00+00:00"
    resources = (
        (ResourceRecord(resource_id="substituted", type="compute.vm"),)
        if defect == "resource"
        else ()
    )
    arguments = dict(
        key=key,
        pending=pending,
        publication=publication,
        recorded_at=None if defect == "missing_snapshot" else observation.recorded_at,
        resources=resources,
    )
    if defect is not None:
        with pytest.raises(ValueError, match="inventory delivery recovery"):
            verified_delivery_observation(**arguments)
    else:
        assert verified_delivery_observation(**arguments) == observation


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
