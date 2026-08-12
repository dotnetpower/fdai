"""Adversarial complete-generation fixtures for provider relationships."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.shared.providers.inventory import (
    LinkRecord,
    ProviderRelationshipEvidence,
    RelationshipDropReason,
    ResourceRecord,
)

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
OBSERVED_AT = "2026-08-12T11:59:00Z"


def _resource(resource_id: str, type_id: str) -> ResourceRecord:
    return ResourceRecord(resource_id=resource_id, type=type_id, last_seen=OBSERVED_AT)


def _evidence(
    *,
    mapping_id: str = "azure.vm-nic-attached-to-vm",
    owner_id: str = "vm-1",
    observation_receipt_ref: str = "sha256:" + "1" * 64,
) -> ProviderRelationshipEvidence:
    return ProviderRelationshipEvidence(
        mapping_id=mapping_id,
        mapping_revision="sha256:" + "2" * 64,
        mapping_receipt_ref="catalog-receipt:azure-arg-v1",
        provider_identity="azure",
        source_identity="azure-resource-graph",
        source_property_path="properties.networkProfile.networkInterfaces[].id",
        source_schema_version="azure-resource-graph-resources@2022-10-01",
        source_schema_digest="sha256:" + "3" * 64,
        observed_schema_digest="sha256:" + "3" * 64,
        evidence_method="deterministic-cross-check",
        freshness_ceiling_seconds=21600,
        endpoint_orientation="referenced_to_owner",
        provider_owner_id=owner_id,
        observation_receipt_ref=observation_receipt_ref,
    )


def _link(
    from_id: str = "nic-1",
    to_id: str = "vm-1",
    *,
    from_type: str = "network.interface",
    to_type: str = "compute.vm",
    link_type: str = "attached_to",
    evidence: ProviderRelationshipEvidence | None = None,
) -> LinkRecord:
    return LinkRecord(
        from_id=from_id,
        from_type=from_type,
        link_type=link_type,
        to_id=to_id,
        to_type=to_type,
        mapping_evidence=evidence or _evidence(),
    )


def _verify(
    *,
    resources: tuple[ResourceRecord, ...] | None = None,
    links: tuple[LinkRecord, ...] | None = None,
    complete: bool = True,
    verifier_identity: str | None = "inventory-generation-verifier",
):
    return verify_inventory_relationships(
        generation="generation-1",
        resources=resources
        if resources is not None
        else (_resource("nic-1", "network.interface"), _resource("vm-1", "compute.vm")),
        links=links if links is not None else (_link(),),
        complete=complete,
        recorded_at=NOW,
        verifier_identity=verifier_identity,
    )


def test_complete_generation_verifies_link_with_mapping_metadata() -> None:
    result = _verify()

    assert result.dropped == ()
    metadata = result.links[0].observation_metadata
    assert metadata is not None
    assert metadata.verified is True
    assert metadata.inventory_generation == "generation-1"
    assert metadata.mapping_id == "azure.vm-nic-attached-to-vm"
    assert metadata.verifier_identity != metadata.state_fact.source_identity
    assert metadata.verification_receipt_ref.startswith("sha256:")


def test_missing_source_endpoint_is_absent_and_reported() -> None:
    result = _verify(resources=(_resource("vm-1", "compute.vm"),))
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {
        RelationshipDropReason.MISSING_SOURCE_ENDPOINT
    }


def test_missing_target_endpoint_is_absent_and_reported() -> None:
    result = _verify(resources=(_resource("nic-1", "network.interface"),))
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {
        RelationshipDropReason.MISSING_TARGET_ENDPOINT
    }


def test_duplicate_edge_fails_closed() -> None:
    edge = _link()
    result = _verify(links=(edge, edge))
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {RelationshipDropReason.DUPLICATE_EDGE}


def test_conflicting_duplicate_fails_closed() -> None:
    result = _verify(links=(_link(), replace(_link(), link_props={"conflict": True})))
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {
        RelationshipDropReason.CONFLICTING_DUPLICATE
    }


def test_partial_generation_claims_no_links() -> None:
    result = _verify(complete=False)
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {RelationshipDropReason.PARTIAL_GENERATION}


def test_stale_source_schema_digest_is_absent_and_reported() -> None:
    stale = replace(_evidence(), observed_schema_digest="sha256:" + "4" * 64)
    result = _verify(links=(_link(evidence=stale),))
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {
        RelationshipDropReason.STALE_SOURCE_SCHEMA_DIGEST
    }


def test_missing_independent_verifier_is_absent_and_reported() -> None:
    result = _verify(verifier_identity=None)
    assert result.links == ()
    assert {drop.reason for drop in result.dropped} == {
        RelationshipDropReason.MISSING_INDEPENDENT_VERIFIER
    }


def test_symmetric_peering_has_independent_direction_receipts() -> None:
    resources = (_resource("vnet-a", "network.vnet"), _resource("vnet-b", "network.vnet"))
    forward_evidence = _evidence(
        mapping_id="azure.vnet-peered-with-vnet",
        owner_id="vnet-a",
        observation_receipt_ref="sha256:" + "a" * 64,
    )
    reverse_evidence = _evidence(
        mapping_id="azure.vnet-peered-with-vnet",
        owner_id="vnet-b",
        observation_receipt_ref="sha256:" + "b" * 64,
    )
    result = _verify(
        resources=resources,
        links=(
            _link(
                "vnet-a",
                "vnet-b",
                from_type="network.vnet",
                to_type="network.vnet",
                link_type="peered_with",
                evidence=forward_evidence,
            ),
            _link(
                "vnet-b",
                "vnet-a",
                from_type="network.vnet",
                to_type="network.vnet",
                link_type="peered_with",
                evidence=reverse_evidence,
            ),
        ),
    )

    assert result.dropped == ()
    receipts = {
        link.observation_metadata.verification_receipt_ref
        for link in result.links
        if link.observation_metadata is not None
    }
    assert len(receipts) == 2
