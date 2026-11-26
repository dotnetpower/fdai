"""Competency queries for the FDAI operating semantic spine."""

from __future__ import annotations

from pathlib import Path

from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[4]
AT = "2026-07-31T00:00:00Z"


async def test_service_impact_query_reaches_resources_objectives_and_owner() -> None:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )

    records = (
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": AT,
                "source_ref": "service-catalog:example",
            },
        ),
        OntologyObjectRecord(
            id="workload-example",
            object_type="Workload",
            properties={
                "id": "workload-example",
                "name": "Example Workload",
                "workload_kind": "api",
                "effective_from": AT,
                "source_ref": "service-manifest:example",
            },
        ),
        OntologyObjectRecord(
            id="resource-example",
            object_type="Resource",
            properties={"id": "resource-example", "type": "app-service"},
        ),
        OntologyObjectRecord(
            id="slo-example",
            object_type="ServiceObjective",
            properties={
                "id": "slo-example",
                "objective_kind": "availability",
                "metric": "successful_request_ratio",
                "unit": "ratio",
                "target": 0.999,
                "window_seconds": 2592000,
                "measurement_source_ref": "metrics:availability",
                "freshness_seconds": 300,
                "effective_from": AT,
            },
        ),
        OntologyObjectRecord(
            id="owner-example",
            object_type="Ownership",
            properties={
                "id": "owner-example",
                "owner_ref": "group:service-owner",
                "escalation_ref": "oncall:service-owner",
                "effective_from": AT,
                "source_ref": "service-catalog:ownership",
            },
        ),
    )
    for record in records:
        await store.upsert_object(record)
    for link in (
        OntologyLinkRecord(
            link_type="implemented_by",
            from_id="service-example",
            to_id="workload-example",
        ),
        OntologyLinkRecord(
            link_type="workload_runs_on",
            from_id="workload-example",
            to_id="resource-example",
        ),
        OntologyLinkRecord(
            link_type="service_has_service_objective",
            from_id="service-example",
            to_id="slo-example",
        ),
        OntologyLinkRecord(
            link_type="service_owned_by",
            from_id="service-example",
            to_id="owner-example",
        ),
    ):
        await store.upsert_link(link)

    impact = await store.traverse(
        root_ids=("service-example",),
        direction="outgoing",
        max_depth=2,
    )

    assert {item.id for item in impact.objects} == {
        "service-example",
        "workload-example",
        "resource-example",
        "slo-example",
        "owner-example",
    }
    assert {item.link_type for item in impact.links} == {
        "implemented_by",
        "workload_runs_on",
        "service_has_service_objective",
        "service_owned_by",
    }
