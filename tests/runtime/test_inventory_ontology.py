"""Single-writer ownership for the provider-observed resource subgraph."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.inventory_ontology import (
    INVENTORY_ONTOLOGY_MANIFEST_KEY,
    InventoryOntologyProjector,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _observation(
    *,
    generation: str,
    resource_ids: tuple[str, ...],
    links: tuple[LinkRecord, ...] = (),
    complete: bool = True,
) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation=generation,
        resources=tuple(
            ResourceRecord(resource_id=item, type="compute.vm", props={"name": item})
            for item in resource_ids
        ),
        links=links,
        complete=complete,
    )


async def test_first_generation_writes_owned_objects_and_manifest() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)

    result = await projector.apply(
        _observation(
            generation="snapshot-1",
            resource_ids=("vm-1", "vm-2"),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="Resource",
                    link_type="depends_on",
                    to_id="vm-2",
                    to_type="Resource",
                ),
            ),
        )
    )

    assert result.generation == "snapshot-1"
    assert result.object_count == 2
    assert result.link_count == 1
    assert result.complete is True

    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert sorted(manifest["object_ids"]) == ["vm-1", "vm-2"]
    assert manifest["generation"] == "snapshot-1"


async def test_next_generation_deletes_disappeared_resources() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)

    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1", "vm-2")))
    await projector.apply(_observation(generation="snapshot-2", resource_ids=("vm-1",)))

    assert await store.get_object("vm-1") is not None
    assert await store.get_object("vm-2") is None


async def test_repeated_generation_is_idempotent() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)

    first = await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))
    second = await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    assert first.object_count == second.object_count == 1
    assert await store.get_object("vm-1") is not None


async def test_foreign_owned_object_is_rejected() -> None:
    store = _store()
    status = InMemoryStateStore()
    await store.upsert_object(
        OntologyObjectRecord(
            id="vm-1",
            object_type="Resource",
            properties={"id": "vm-1", "type": "compute.vm"},
        )
    )
    projector = InventoryOntologyProjector(store=store, status_store=status)

    with pytest.raises(OntologyInstanceValidationError, match="owned by another projection"):
        await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))


async def test_incomplete_observation_records_coverage() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)

    result = await projector.apply(
        _observation(generation="snapshot-1", resource_ids=("vm-1",), complete=False)
    )

    assert result.complete is False
    assert "observation_incomplete" in result.dropped_reasons
    manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    assert manifest is not None
    assert manifest["complete"] is False
