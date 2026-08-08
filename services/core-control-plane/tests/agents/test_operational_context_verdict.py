from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai.agents.forseti import Forseti
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _store() -> InMemoryOntologyInstanceStore:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    return InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )


async def _add_resource(store: InMemoryOntologyInstanceStore) -> None:
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource-example",
            object_type="Resource",
            properties={"id": "resource-example", "type": "app-service"},
        )
    )


async def test_unmapped_operational_context_lowers_auto_verdict_to_hil() -> None:
    store = _store()
    await _add_resource(store)
    forseti = Forseti(
        operational_context=OperationalContextMaterializer(store=store, clock=lambda: NOW)
    )

    verdict = await forseti.judge(
        {
            "event_type": "restart_needed",
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "detected_at": NOW.isoformat(),
            "catalog_versions": {"ontology": "1.0.0"},
        }
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "operational_context_ceiling"
    assert verdict["operational_context"]["conflicts"] == ["service_mapping_missing"]


async def test_fresh_operational_context_preserves_auto_verdict() -> None:
    store = _store()
    await _add_resource(store)
    for record in (
        OntologyObjectRecord(
            id="workload-example",
            object_type="Workload",
            properties={
                "id": "workload-example",
                "name": "Example Workload",
                "workload_kind": "api",
                "effective_from": NOW.isoformat(),
                "source_ref": "service-manifest:example",
            },
        ),
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": NOW.isoformat(),
                "source_ref": "service-catalog:example",
            },
        ),
    ):
        await store.upsert_object(record)
    for link in (
        OntologyLinkRecord(
            link_type="workload_runs_on",
            from_id="workload-example",
            to_id="resource-example",
        ),
        OntologyLinkRecord(
            link_type="implemented_by",
            from_id="service-example",
            to_id="workload-example",
        ),
    ):
        await store.upsert_link(link)
    forseti = Forseti(
        operational_context=OperationalContextMaterializer(store=store, clock=lambda: NOW)
    )

    verdict = await forseti.judge(
        {
            "event_type": "restart_needed",
            "correlation_id": "correlation-example",
            "resource_id": "resource-example",
            "detected_at": NOW.isoformat(),
            "catalog_versions": {"ontology": "1.0.0"},
        }
    )

    assert verdict is not None
    assert verdict["risk_verdict"] == "auto"
    assert verdict["operational_context"]["service_ids"] == ["service-example"]
