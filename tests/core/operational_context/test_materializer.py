from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.models import Autonomy
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[3]
CUTOFF = datetime(2026, 7, 31, tzinfo=UTC)


class _TruncatedOntologyStore:
    def __init__(self, graph: OntologyGraphSnapshot) -> None:
        self._graph = graph

    async def get_object(self, object_id: str) -> OntologyObjectRecord | None:
        return next((item for item in self._graph.objects if item.id == object_id), None)

    async def traverse(self, **_: object) -> OntologyGraphSnapshot:
        return self._graph


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
    freshness = (
        SourceFreshness(
            source="inventory",
            observed_at=CUTOFF - timedelta(seconds=30),
            max_age_seconds=300,
        ),
    )

    first = await materializer.materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0", "rules": "2026.07"},
        source_freshness=freshness,
    )
    replay = await materializer.materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0", "rules": "2026.07"},
        source_freshness=freshness,
    )

    assert first.snapshot_id == replay.snapshot_id
    assert first.service_ids == ("service-example",)
    assert first.workload_ids == ("workload-example",)
    assert first.objective_ids == ("slo-example",)
    assert first.source_freshness == freshness
    assert tuple((item.link_type, item.from_id, item.to_id) for item in first.evidence_links) == (
        ("implemented_by", "service-example", "workload-example"),
        ("service_has_service_objective", "service-example", "slo-example"),
        ("workload_runs_on", "workload-example", "resource-example"),
    )
    paths = {item.object_id: item for item in first.evidence_paths}
    assert paths["resource-example"].links == ()
    assert paths["service-example"].effective_from == CUTOFF
    assert paths["service-example"].effective_to is None
    assert paths["service-example"].provenance_refs == ("service-catalog:example",)
    assert paths["slo-example"].provenance_refs == ("metrics:availability",)
    assert [item.link_type for item in paths["service-example"].links] == [
        "workload_runs_on",
        "implemented_by",
    ]
    assert [item.link_type for item in paths["slo-example"].links] == [
        "workload_runs_on",
        "implemented_by",
        "service_has_service_objective",
    ]
    assert first.autonomy_ceiling is Autonomy.ENFORCE_AUTO
    assert first.review_required is False


async def test_revision_and_freshness_receipts_change_snapshot_identity() -> None:
    store = _store()
    await _seed_service_graph(store)
    materializer = OperationalContextMaterializer(store=store, clock=lambda: CUTOFF)
    base = await materializer.materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0"},
        source_freshness=(
            SourceFreshness(
                source="inventory",
                observed_at=CUTOFF - timedelta(seconds=30),
                max_age_seconds=300,
            ),
        ),
    )
    fresher = await materializer.materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0"},
        source_freshness=(
            SourceFreshness(
                source="inventory",
                observed_at=CUTOFF - timedelta(seconds=20),
                max_age_seconds=300,
            ),
        ),
    )
    await store.upsert_object(
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
        expected_revision=1,
    )
    revised = await materializer.materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0"},
        source_freshness=base.source_freshness,
    )

    assert base.snapshot_id != fresher.snapshot_id
    assert base.snapshot_id != revised.snapshot_id
    assert {item.object_id: item.revision for item in revised.evidence_paths}[
        "service-example"
    ] == 2


async def test_truncated_graph_lowers_autonomy() -> None:
    resource = OntologyObjectRecord(
        id="resource-example",
        object_type="Resource",
        properties={"id": "resource-example", "type": "app-service"},
        revision=1,
    )
    store = cast(
        OntologyInstanceStore,
        _TruncatedOntologyStore(
            OntologyGraphSnapshot(objects=(resource,), truncated=True),
        ),
    )
    snapshot = await OperationalContextMaterializer(store=store, clock=lambda: CUTOFF).materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0"},
    )

    assert "context_graph_truncated" in snapshot.conflicts
    assert snapshot.autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert snapshot.review_required is True


async def test_future_effective_context_is_excluded_and_lowers_autonomy() -> None:
    store = _store()
    await _seed_service_graph(store)
    await store.upsert_object(
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": (CUTOFF + timedelta(seconds=1)).isoformat(),
                "source_ref": "service-catalog:future",
            },
        ),
        expected_revision=1,
    )

    snapshot = await OperationalContextMaterializer(store=store, clock=lambda: CUTOFF).materialize(
        target_resource_id="resource-example",
        cutoff=CUTOFF,
        catalog_versions={"ontology": "1.0.0"},
    )

    assert snapshot.service_ids == ()
    assert snapshot.objective_ids == ()
    assert snapshot.temporal_exclusions[0].object_id == "service-example"
    assert snapshot.temporal_exclusions[0].provenance_refs == ("service-catalog:future",)
    assert "context_temporal_exclusion" in snapshot.conflicts
    assert "service_mapping_missing" in snapshot.conflicts
    assert snapshot.autonomy_ceiling is Autonomy.SHADOW_ONLY


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
