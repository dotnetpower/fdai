"""Incident lifecycle projection into the current ontology instance graph."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fdai.core.incident import IncidentOntologyProjector, IncidentRegistry
from fdai.core.ontology_platform import (
    CompiledInterfaceCatalog,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[5]


async def test_registry_projects_rehydrated_and_live_incident_into_object_set() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    ontology_store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)
    opened_at = datetime(2026, 8, 14, 9, tzinfo=UTC)
    incident = await registry.open(
        correlation_keys=("resource:example",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
        opened_at=opened_at,
    )

    entries = await state_store.read_incident_transitions()
    restored = IncidentRegistry(state_store=state_store)
    restored.rehydrate(entries)
    await restored.bind_projection(
        IncidentOntologyProjector(store=ontology_store),
        entries=entries,
    )

    object_sets = ObjectSetService(
        store=ontology_store,
        interfaces=CompiledInterfaceCatalog(interfaces={}, concrete_types={}),
        object_type_names=frozenset(item.name for item in catalog.object_types),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Incident"),
        as_of=opened_at,
        purpose="operations-review",
    )
    initial = await object_sets.materialize(definition)

    assert len(initial.graph.objects) == 1
    projected = initial.graph.objects[0]
    assert projected.id == str(incident.incident_id)
    assert projected.properties == {
        "correlation_id": str(incident.incident_id),
        "id": str(incident.incident_id),
        "opened_at": "2026-08-14T09:00:00Z",
        "severity": "sev2",
        "status": "open",
        "updated_at": "2026-08-14T09:00:00Z",
    }

    transitioned_at = datetime(2026, 8, 14, 9, 5, tzinfo=UTC)
    await restored.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
        at=transitioned_at,
    )
    current = await object_sets.materialize(definition)

    assert current.graph.objects[0].properties["status"] == "triaging"
    assert current.graph.objects[0].properties["updated_at"] == "2026-08-14T09:05:00Z"
    assert current.graph.objects[0].revision == 2
