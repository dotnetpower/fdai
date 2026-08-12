"""Single-writer ownership for the provider-observed resource subgraph."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore, InMemoryStateStore

REPO_ROOT = Path(__file__).resolve().parents[4]


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
    attach_metadata: bool = True,
) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation=generation,
        resources=tuple(
            ResourceRecord(resource_id=item, type="compute.vm", props={"name": item})
            for item in resource_ids
        ),
        links=tuple(
            replace(link, observation_metadata=_metadata(generation, index))
            for index, link in enumerate(links)
        )
        if attach_metadata
        else links,
        complete=complete,
    )


def _metadata(generation: str, index: int) -> LinkObservationMetadata:
    recorded_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-provider",
            source_revision="provider-schema-v1",
            effective_at=recorded_at - timedelta(minutes=1),
            recorded_at=recorded_at,
            evidence_cutoff=recorded_at - timedelta(minutes=1),
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(f"inventory-receipt-{index}",),
        ),
        verification_method="deterministic-cross-check",
        verified=True,
        verifier_identity="inventory-generation-verifier",
        verifier_revision="verifier-v1",
        verification_receipt_ref=f"verification-receipt-{index}",
        inventory_generation=generation,
        mapping_id=f"test.mapping-{index}",
        mapping_revision="sha256:" + "1" * 64,
        source_schema_version="provider-schema-v1",
        source_schema_digest="sha256:" + "2" * 64,
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
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="vm-2",
                    to_type="compute.vm",
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


async def test_projector_persists_resource_type_classification() -> None:
    store = _store()
    status = InMemoryStateStore()
    await store.upsert_object(
        OntologyObjectRecord(
            id="compute.vm",
            object_type="ResourceType",
            properties={"id": "compute.vm", "category": "compute"},
        )
    )
    projector = InventoryOntologyProjector(
        store=store,
        status_store=status,
        resource_type_mappings={"compute.vm": "sha256:" + ("a" * 64)},
    )

    result = await projector.apply(
        _observation(generation="snapshot-classified", resource_ids=("vm-1",))
    )

    assert result.complete is True
    assert result.link_count == 1
    graph = await store.traverse(
        root_ids=("vm-1",),
        link_types=("resource_classified_as",),
        max_depth=1,
        limit=10,
    )
    assert [(item.from_id, item.to_id) for item in graph.links] == [("vm-1", "compute.vm")]


async def test_one_resource_can_retain_multiple_observed_attachments() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)

    result = await projector.apply(
        _observation(
            generation="snapshot-attachments",
            resource_ids=("vm-1", "network-1", "disk-1"),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="attached_to",
                    to_id="network-1",
                    to_type="compute.vm",
                ),
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="attached_to",
                    to_id="disk-1",
                    to_type="compute.vm",
                ),
            ),
        )
    )

    assert result.link_count == 2


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


async def test_incomplete_observation_preserves_prior_projection_and_records_unavailable() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)

    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))
    prior_manifest = await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    result = await projector.apply(
        _observation(generation="snapshot-2", resource_ids=("vm-2",), complete=False)
    )

    assert result.complete is False
    assert "observation_incomplete" in result.dropped_reasons
    assert getattr(result, "status", None) == "unavailable"
    assert await store.get_object("vm-1") is not None
    assert await store.get_object("vm-2") is None
    assert await status.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY) == prior_manifest
    assert await status.read_state("inventory-ontology:status") == {
        "schema_version": "1.0.0",
        "generation": "snapshot-2",
        "status": "unavailable",
        "dropped_reasons": ["observation_incomplete"],
    }


async def test_metadata_less_link_preserves_prior_projection_and_reports_unverified() -> None:
    store = _store()
    status = InMemoryStateStore()
    projector = InventoryOntologyProjector(store=store, status_store=status)
    await projector.apply(_observation(generation="snapshot-1", resource_ids=("vm-1",)))

    result = await projector.apply(
        _observation(
            generation="snapshot-2",
            resource_ids=("vm-1", "vm-2"),
            links=(
                LinkRecord(
                    from_id="vm-1",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="vm-2",
                    to_type="compute.vm",
                ),
            ),
            attach_metadata=False,
        )
    )

    assert result.status == "unavailable"
    assert result.link_count == 0
    assert "unverified_metadata" in result.dropped_reasons
    assert await store.get_object("vm-2") is None
