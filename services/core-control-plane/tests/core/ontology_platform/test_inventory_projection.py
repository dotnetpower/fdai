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


def _link(
    from_id: str,
    link_type: str,
    to_id: str,
    *,
    from_type: str = "compute.vm",
    to_type: str = "compute.vm",
) -> LinkRecord:
    return LinkRecord(
        from_id=from_id,
        from_type=from_type,
        link_type=link_type,
        to_id=to_id,
        to_type=to_type,
        observation_metadata=_observation_metadata(),
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
        verification_receipt_ref="verification-receipt-3",
        inventory_generation="snapshot-1",
        mapping_id="test.mapping",
        mapping_revision="sha256:" + "1" * 64,
        source_schema_version="test-schema-v1",
        source_schema_digest="sha256:" + "2" * 64,
    )


def test_complete_observation_projects_typed_objects_and_links() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            _resource("rg-1", type_id="resource-group", name="group-one"),
            _resource("vm-1", name="vm-one", parent_id="rg-1"),
        ),
        links=(
            _link(
                "rg-1",
                "contains",
                "vm-1",
                from_type="resource-group",
                to_type="compute.vm",
            ),
        ),
    )

    assert projection.generation == "snapshot-1"
    assert [item.id for item in projection.objects] == ["rg-1", "vm-1"]
    assert all(item.object_type == "Resource" for item in projection.objects)
    assert [(item.link_type, item.from_id, item.to_id) for item in projection.links] == [
        ("contains", "rg-1", "vm-1")
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
                from_id="rg-1",
                from_type="resource-group",
                link_type="contains",
                to_id="vm-1",
                to_type="compute.vm",
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
        links=(
            _link(
                "rg-1",
                "contains",
                "vm-1",
                from_type="resource-group",
                to_type="compute.vm",
            ),
        ),
        observation_complete=False,
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "observation_incomplete" in projection.dropped_reasons


def test_unregistered_link_type_is_dropped_and_reported() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("vm-2")),
        links=(_link("vm-1", "unknown_network_link", "vm-2"),),
    )

    assert projection.links == ()
    assert projection.complete is False
    assert "unregistered_link_type" in projection.dropped_reasons


def test_catalog_declared_network_links_are_projected_as_directed_records() -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(
            _resource("nic-1", type_id="network.nic"),
            _resource("route-1", type_id="network.route"),
            _resource("vnet-1", type_id="network.vnet"),
            _resource("vnet-2", type_id="network.vnet"),
        ),
        links=(
            _link(
                "nic-1",
                "routes_to",
                "route-1",
                from_type="network.nic",
                to_type="network.route",
            ),
            _link(
                "vnet-1",
                "peered_with",
                "vnet-2",
                from_type="network.vnet",
                to_type="network.vnet",
            ),
            _link(
                "vnet-2",
                "peered_with",
                "vnet-1",
                from_type="network.vnet",
                to_type="network.vnet",
            ),
        ),
    )

    assert [(item.link_type, item.from_id, item.to_id) for item in projection.links] == [
        ("peered_with", "vnet-1", "vnet-2"),
        ("peered_with", "vnet-2", "vnet-1"),
        ("routes_to", "nic-1", "route-1"),
    ]


@pytest.mark.parametrize(
    ("resources", "links", "expected_reason"),
    (
        (
            (_resource("vm-1"),),
            (
                _link(
                    "rg-missing",
                    "contains",
                    "vm-1",
                    from_type="resource-group",
                    to_type="compute.vm",
                ),
            ),
            "missing_source_endpoint",
        ),
        (
            (_resource("rg-1", type_id="resource-group"),),
            (
                _link(
                    "rg-1",
                    "contains",
                    "vm-missing",
                    from_type="resource-group",
                    to_type="compute.vm",
                ),
            ),
            "missing_target_endpoint",
        ),
    ),
)
def test_unobserved_endpoint_is_dropped_and_reported(
    resources: tuple[ResourceRecord, ...],
    links: tuple[LinkRecord, ...],
    expected_reason: str,
) -> None:
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=resources,
        links=links,
    )

    assert projection.links == ()
    assert projection.complete is False
    assert expected_reason in projection.dropped_reasons


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


def test_conflicting_duplicate_link_is_absent_and_reported() -> None:
    metadata = _observation_metadata()
    projection = build_inventory_ontology_projection(
        generation="snapshot-1",
        resources=(_resource("vm-1"), _resource("vm-2")),
        links=(
            LinkRecord(
                "vm-1",
                "compute.vm",
                "depends_on",
                "vm-2",
                "compute.vm",
                observation_metadata=metadata,
            ),
            LinkRecord(
                "vm-1",
                "compute.vm",
                "depends_on",
                "vm-2",
                "compute.vm",
                link_props={"observation": "different"},
                observation_metadata=metadata,
            ),
        ),
    )

    assert projection.links == ()
    assert "conflicting_duplicate" in projection.dropped_reasons


def test_link_endpoint_types_must_match_observed_resource_types() -> None:
    with pytest.raises(InventoryProjectionConflictError, match="endpoint type"):
        build_inventory_ontology_projection(
            generation="snapshot-1",
            resources=(
                _resource("nic-1", type_id="network.nic"),
                _resource("route-1", type_id="network.route"),
            ),
            links=(
                _link(
                    "nic-1",
                    "routes_to",
                    "route-1",
                    from_type="network.vnet",
                    to_type="network.route",
                ),
            ),
        )


def test_generation_is_required() -> None:
    with pytest.raises(ValueError, match="generation"):
        build_inventory_ontology_projection(generation="  ", resources=(_resource("vm-1"),))
