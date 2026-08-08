"""Coverage-honest projection of inventory observations into the resource subgraph."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.ontology_platform.inventory_projection import (
    InventoryProjectionConflictError,
    build_inventory_ontology_projection,
)
from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

OBSERVED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _resource(resource_id: str, *, type_id: str = "compute.vm", **props: str) -> ResourceRecord:
    return ResourceRecord(resource_id=resource_id, type=type_id, props=dict(props))


def _link(from_id: str, link_type: str, to_id: str) -> LinkRecord:
    return LinkRecord(
        from_id=from_id,
        from_type="Resource",
        link_type=link_type,
        to_id=to_id,
        to_type="Resource",
    )


def _observation_metadata() -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="inventory-provider",
            source_revision="revision-7",
            effective_at=OBSERVED_AT - timedelta(seconds=30),
            evidence_cutoff=OBSERVED_AT - timedelta(seconds=20),
            recorded_at=OBSERVED_AT,
            freshness_ceiling_seconds=300,
            completeness=1.0,
            synthetic=False,
            evidence_refs=("inventory-receipt-7",),
        ),
        verification_method="provider-readback",
        verified=True,
        verifier_identity="inventory-readback",
        verifier_revision="revision-3",
    )


def test_complete_observation_projects_typed_objects_and_links() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            _resource("rg-1", type_id="resource-group", name="group-one"),
            _resource("vm-1", name="vm-one", parent_id="rg-1"),
        ),
        links=(_link("vm-1", "contains", "rg-1"),),
    )

    assert projection.generation == "snapshot-1"
    assert [item.id for item in projection.objects] == ["rg-1", "vm-1"]
    assert all(item.object_type == "Resource" for item in projection.objects)
    assert [(item.link_type, item.from_id, item.to_id) for item in projection.links] == [
        ("contains", "vm-1", "rg-1")
    ]
    assert projection.complete is True
    assert projection.dropped_reasons == ()

    vm = next(item for item in projection.objects if item.id == "vm-1")
    assert vm.properties["type"] == "compute.vm"
    assert vm.properties["name"] == "vm-one"
    assert vm.properties["parent_id"] == "rg-1"


def test_link_observation_metadata_is_projected_canonically() -> None:
    metadata = _observation_metadata()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("rg-1", type_id="resource-group")),
        links=(
            LinkRecord(
                from_id="vm-1",
                from_type="Resource",
                link_type="contains",
                to_id="rg-1",
                to_type="Resource",
                observation_metadata=metadata,
            ),
        ),
    )

    assert projection.links[0].properties[LINK_OBSERVATION_METADATA_PROPERTY] == (
        metadata.to_mapping()
    )


def test_incomplete_observation_claims_no_relationship() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("rg-1", type_id="resource-group")),
        links=(_link("vm-1", "contains", "rg-1"),),
        observation_complete=False,
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "observation_incomplete" in projection.dropped_reasons


def test_unregistered_link_type_is_dropped_and_reported() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("vm-2")),
        links=(_link("vm-1", "peered_with", "vm-2"),),
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "unregistered_link_type" in projection.dropped_reasons


def test_unobserved_endpoint_is_dropped_and_reported() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"),),
        links=(_link("vm-1", "contains", "rg-missing"),),
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "unobserved_endpoint" in projection.dropped_reasons


def test_self_reference_is_dropped_and_reported() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"),),
        links=(_link("vm-1", "contains", "vm-1"),),
    )

    assert projection.links == ()
    assert "self_reference" in projection.dropped_reasons


def test_repeated_identical_observation_is_idempotent() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1", name="vm-one"), _resource("vm-1", name="vm-one")),
        links=(_link("vm-1", "contains", "vm-1"),) * 0,
    )

    assert [item.id for item in projection.objects] == ["vm-1"]


def test_conflicting_observation_for_one_id_is_rejected() -> None:
    with pytest.raises(InventoryProjectionConflictError):
        build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(_resource("vm-1", name="vm-one"), _resource("vm-1", name="vm-two")),
        )


def test_generation_is_required() -> None:
    with pytest.raises(ValueError, match="generation"):
        build_inventory_ontology_projection(generation="  ", resources=(_resource("vm-1"),))
