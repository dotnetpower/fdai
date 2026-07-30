from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.models import Autonomy
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[3]
CUTOFF = datetime(2026, 7, 31, tzinfo=UTC)


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


async def _seed_service_graph(store: InMemoryOntologyInstanceStore) -> None:
    for record in (
        OntologyObjectRecord(
            id="resource-example",
            object_type="Resource",
            properties={"id": "resource-example", "type": "app-service"},
        ),
        OntologyObjectRecord(
            id="workload-example",
            object_type="Workload",
            properties={
                "id": "workload-example",
                "name": "Example Workload",
                "workload_kind": "api",
                "effective_from": CUTOFF.isoformat(),
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
                "effective_from": CUTOFF.isoformat(),
                "source_ref": "service-catalog:example",
            },
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
                "effective_from": CUTOFF.isoformat(),
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
        OntologyLinkRecord(
            link_type="service_has_service_objective",
            from_id="service-example",
            to_id="slo-example",
        ),
    ):
        await store.upsert_link(link)


async def test_fresh_context_preserves_autonomy_and_replays() -> None:
    store = _store()
    await _seed_service_graph(store)
    materializer = OperationalContextMaterializer(store=store, clock=lambda: CUTOFF)
    kwargs = {
        "target_resource_id": "resource-example",
        "cutoff": CUTOFF,
        "catalog_versions": {"ontology": "1.0.0", "rules": "2026.07"},
        "source_freshness": (
            SourceFreshness(
                source="inventory",
                observed_at=CUTOFF - timedelta(seconds=30),
                max_age_seconds=300,
            ),
        ),
    }

    first = await materializer.materialize(**kwargs)
    replay = await materializer.materialize(**kwargs)

    assert first.snapshot_id == replay.snapshot_id
    assert first.service_ids == ("service-example",)
    assert first.workload_ids == ("workload-example",)
    assert first.objective_ids == ("slo-example",)
    assert first.autonomy_ceiling is Autonomy.ENFORCE_AUTO
    assert first.review_required is False


async def test_unmapped_or_stale_context_lowers_autonomy() -> None:
    store = _store()
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource-example",
            object_type="Resource",
            properties={"id": "resource-example", "type": "app-service"},
        )
    )
    materializer = OperationalContextMaterializer(store=store, clock=lambda: CUTOFF)

    snapshot = await materializer.materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0"},
        source_freshness=(
            SourceFreshness(
                source="inventory",
                observed_at=CUTOFF - timedelta(hours=1),
                max_age_seconds=300,
            ),
        ),
    )

    assert snapshot.conflicts == ("service_mapping_missing",)
    assert snapshot.stale_sources == ("inventory",)
    assert snapshot.autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert snapshot.review_required is True
