from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.operational_context import OperatingModelProjector
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

REPO_ROOT = Path(__file__).resolve().parents[3]
AT = "2026-07-31T00:00:00Z"


def _projector() -> tuple[OperatingModelProjector, InMemoryOntologyInstanceStore]:
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    return (
        OperatingModelProjector(
            store=store,
            object_types=catalog.object_types,
            link_types=catalog.link_types,
        ),
        store,
    )


def _objects() -> tuple[OntologyObjectRecord, ...]:
    return (
        OntologyObjectRecord(
            id="service-example",
            object_type="BusinessService",
            properties={
                "id": "service-example",
                "name": "Example Service",
                "criticality": "high",
                "effective_from": AT,
                "source_ref": "catalog:service",
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
                "source_ref": "catalog:workload",
            },
        ),
    )


async def test_invalid_late_link_writes_nothing_to_real_store() -> None:
    projector, store = _projector()
    snapshot = OperatingModelSnapshot(
        source_revision="revision-1",
        objects=_objects(),
        links=(
            OntologyLinkRecord(
                link_type="implemented_by",
                from_id="workload-example",
                to_id="service-example",
            ),
        ),
    )

    with pytest.raises(OntologyInstanceValidationError, match="requires"):
        await projector.project(snapshot)

    assert await store.get_object("service-example") is None
    assert await store.get_object("workload-example") is None


async def test_valid_snapshot_projects_objects_and_links() -> None:
    projector, store = _projector()
    snapshot = OperatingModelSnapshot(
        source_revision="revision-1",
        objects=_objects(),
        links=(
            OntologyLinkRecord(
                link_type="implemented_by",
                from_id="service-example",
                to_id="workload-example",
            ),
        ),
    )

    result = await projector.project(snapshot)

    assert result.object_count == 2
    graph = await store.traverse(root_ids=("service-example",), max_depth=1)
    assert {item.id for item in graph.objects} == {"service-example", "workload-example"}


async def test_new_snapshot_atomically_removes_prior_owned_records() -> None:
    projector, store = _projector()
    initial = OperatingModelSnapshot(
        source_revision="revision-1",
        objects=_objects(),
        links=(
            OntologyLinkRecord(
                link_type="implemented_by",
                from_id="service-example",
                to_id="workload-example",
            ),
        ),
    )
    await projector.project(initial)
    replacement = OperatingModelSnapshot(
        source_revision="revision-2",
        objects=(_objects()[0],),
        links=(),
    )

    await projector.project(
        replacement,
        previous_object_ids=("service-example", "workload-example"),
        previous_link_keys=(("service-example", "implemented_by", "workload-example"),),
    )

    assert await store.get_object("service-example") is not None
    assert await store.get_object("workload-example") is None
    graph = await store.traverse(root_ids=("service-example",), max_depth=1)
    assert graph.links == ()
