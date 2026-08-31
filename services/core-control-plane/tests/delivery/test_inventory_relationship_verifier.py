"""Adversarial complete-generation fixtures for provider relationships."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fdai.delivery.azure.arg_projection import (
    arm_id_to_type,
    build_arm_to_neutral_map,
    to_neutral_id,
)
from fdai.delivery.azure.arg_relationships import project_provider_relationships
from fdai.delivery.inventory_relationship_verifier import verify_inventory_relationships
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.shared.providers.inventory import (
    LinkRecord,
    ProviderRelationshipEvidence,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
OBSERVED_AT = "2026-08-12T11:59:00Z"
REPO_ROOT = Path(__file__).resolve().parents[4]


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
        source_provider_type="Microsoft.Compute/virtualMachines",
        target_provider_type="Microsoft.Network/networkInterfaces",
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


def test_complete_generation_verifies_infrastructure_relationship_matrix() -> None:
    catalog = load_provider_relationship_mapping_catalog(
        REPO_ROOT / "rule-catalog" / "vocabulary" / "provider-relationship-mappings"
    )
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    arm_to_neutral = build_arm_to_neutral_map(registry)
    base = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-example/providers"
    ids = {
        "app": f"{base}/Microsoft.App/containerApps/app-example",
        "data_disk": f"{base}/Microsoft.Compute/disks/data-example",
        "identity": (f"{base}/Microsoft.ManagedIdentity/userAssignedIdentities/identity-example"),
        "nic": f"{base}/Microsoft.Network/networkInterfaces/nic-example",
        "nsg": f"{base}/Microsoft.Network/networkSecurityGroups/nsg-example",
        "os_disk": f"{base}/Microsoft.Compute/disks/os-example",
        "private_endpoint": f"{base}/Microsoft.Network/privateEndpoints/endpoint-example",
        "public_ip": f"{base}/Microsoft.Network/publicIPAddresses/ip-example",
        "storage": f"{base}/Microsoft.Storage/storageAccounts/storage-example",
        "subnet": (f"{base}/Microsoft.Network/virtualNetworks/vnet-example/subnets/subnet-example"),
        "vm": f"{base}/Microsoft.Compute/virtualMachines/vm-example",
    }

    def resource(key: str, resource_type: str, provider_type: str) -> ResourceRecord:
        return ResourceRecord(
            resource_id=to_neutral_id(ids[key]),
            type=resource_type,
            provider_ref=ids[key],
            props={"providerType": provider_type},
            last_seen=OBSERVED_AT,
        )

    resources = {
        "app": resource("app", "compute.container-app", "Microsoft.App/containerApps"),
        "data_disk": resource("data_disk", "disk", "Microsoft.Compute/disks"),
        "identity": resource(
            "identity", "managed-identity", "Microsoft.ManagedIdentity/userAssignedIdentities"
        ),
        "nic": resource("nic", "network.interface", "Microsoft.Network/networkInterfaces"),
        "nsg": resource("nsg", "network.nsg", "Microsoft.Network/networkSecurityGroups"),
        "os_disk": resource("os_disk", "disk", "Microsoft.Compute/disks"),
        "private_endpoint": resource(
            "private_endpoint",
            "network.private-endpoint",
            "Microsoft.Network/privateEndpoints",
        ),
        "public_ip": resource(
            "public_ip", "network.public-ip", "Microsoft.Network/publicIPAddresses"
        ),
        "storage": resource("storage", "object-storage", "Microsoft.Storage/storageAccounts"),
        "subnet": resource("subnet", "network.subnet", "Microsoft.Network/virtualNetworks/subnets"),
        "vm": resource("vm", "compute.vm", "Microsoft.Compute/virtualMachines"),
    }
    rows = (
        (
            "vm",
            "Microsoft.Compute/virtualMachines",
            {
                "networkProfile": {"networkInterfaces": [{"id": ids["nic"]}]},
                "storageProfile": {
                    "osDisk": {"managedDisk": {"id": ids["os_disk"]}},
                    "dataDisks": [{"managedDisk": {"id": ids["data_disk"]}}],
                },
            },
            None,
        ),
        (
            "nic",
            "Microsoft.Network/networkInterfaces",
            {
                "ipConfigurations": [
                    {
                        "properties": {
                            "subnet": {"id": ids["subnet"]},
                            "publicIPAddress": {"id": ids["public_ip"]},
                        }
                    }
                ],
                "networkSecurityGroup": {"id": ids["nsg"]},
            },
            None,
        ),
        (
            "app",
            "Microsoft.App/containerApps",
            {},
            {"userAssignedIdentities": {ids["identity"]: {}}},
        ),
        (
            "private_endpoint",
            "Microsoft.Network/privateEndpoints",
            {
                "privateLinkServiceConnections": [
                    {"properties": {"privateLinkServiceId": ids["storage"]}}
                ],
                "subnet": {"id": ids["subnet"]},
            },
            None,
        ),
    )
    expected = {
        "azure.nic-attached-to-nsg": ("nic", "nsg", "attached_to"),
        "azure.nic-attached-to-public-ip": ("nic", "public_ip", "attached_to"),
        "azure.nic-attached-to-subnet": ("nic", "subnet", "attached_to"),
        "azure.private-endpoint-attached-to-service": (
            "private_endpoint",
            "storage",
            "attached_to",
        ),
        "azure.private-endpoint-attached-to-subnet": (
            "private_endpoint",
            "subnet",
            "attached_to",
        ),
        "azure.resource-attached-to-managed-identity": (
            "app",
            "identity",
            "attached_to",
        ),
        "azure.vm-data-disk-attached-to-vm": ("data_disk", "vm", "attached_to"),
        "azure.vm-nic-attached-to-vm": ("nic", "vm", "attached_to"),
        "azure.vm-os-disk-attached-to-vm": ("os_disk", "vm", "attached_to"),
    }
    candidates: list[LinkRecord] = []
    for owner_key, provider_type, properties, identity in rows:
        row: dict[str, object] = {
            "id": ids[owner_key],
            "type": provider_type,
            "properties": properties,
        }
        if identity is not None:
            row["identity"] = identity
        projected = project_provider_relationships(
            row,
            owner=resources[owner_key],
            arm_to_neutral=arm_to_neutral,
            catalog=catalog,
            arm_id_to_type=arm_id_to_type,
            to_neutral_id=to_neutral_id,
        )
        candidates.extend(
            link
            for link in projected.links
            if link.mapping_evidence is not None and link.mapping_evidence.mapping_id in expected
        )

    result = _verify(resources=tuple(resources.values()), links=tuple(candidates))
    reversed_result = _verify(
        resources=tuple(reversed(tuple(resources.values()))),
        links=tuple(reversed(candidates)),
    )

    assert result.dropped == ()
    assert {
        link.mapping_evidence.mapping_id: (
            next(key for key, item in resources.items() if item.resource_id == link.from_id),
            next(key for key, item in resources.items() if item.resource_id == link.to_id),
            link.link_type,
        )
        for link in result.links
        if link.mapping_evidence is not None
    } == expected
    assert reversed_result == result


def test_complete_observed_endpoints_materialize_canonical_core_directions() -> None:
    catalog = load_provider_relationship_mapping_catalog(
        REPO_ROOT / "rule-catalog" / "vocabulary" / "provider-relationship-mappings"
    )
    registry = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    arm_to_neutral = build_arm_to_neutral_map(registry)
    subscription = "00000000-0000-0000-0000-000000000001"
    group_ref = f"/subscriptions/{subscription}/resourceGroups/rg-example"
    base = f"{group_ref}/providers"
    refs = {
        "group": group_ref,
        "vm": f"{base}/Microsoft.Compute/virtualMachines/vm-example",
        "nic": f"{base}/Microsoft.Network/networkInterfaces/nic-example",
        "web": f"{base}/Microsoft.Web/sites/web-example",
        "storage": f"{base}/Microsoft.Storage/storageAccounts/storage-example",
    }
    resources = {
        "group": ResourceRecord(
            resource_id=to_neutral_id(refs["group"]),
            type="resource-group",
            provider_ref=refs["group"],
            props={"providerType": "Microsoft.Resources/resourceGroups"},
            last_seen=OBSERVED_AT,
        ),
        "vm": ResourceRecord(
            resource_id=to_neutral_id(refs["vm"]),
            type="compute.vm",
            provider_ref=refs["vm"],
            props={"providerType": "Microsoft.Compute/virtualMachines"},
            last_seen=OBSERVED_AT,
        ),
        "nic": ResourceRecord(
            resource_id=to_neutral_id(refs["nic"]),
            type="network.interface",
            provider_ref=refs["nic"],
            props={"providerType": "Microsoft.Network/networkInterfaces"},
            last_seen=OBSERVED_AT,
        ),
        "web": ResourceRecord(
            resource_id=to_neutral_id(refs["web"]),
            type="compute.app-service",
            provider_ref=refs["web"],
            props={"providerType": "Microsoft.Web/sites"},
            last_seen=OBSERVED_AT,
        ),
        "storage": ResourceRecord(
            resource_id=to_neutral_id(refs["storage"]),
            type="object-storage",
            provider_ref=refs["storage"],
            props={"providerType": "Microsoft.Storage/storageAccounts"},
            last_seen=OBSERVED_AT,
        ),
    }
    rows = (
        (
            "vm",
            {
                "id": refs["vm"],
                "type": "Microsoft.Compute/virtualMachines",
                "properties": {"networkProfile": {"networkInterfaces": [{"id": refs["nic"]}]}},
            },
        ),
        (
            "web",
            {
                "id": refs["web"],
                "type": "Microsoft.Web/sites",
                "properties": {"storageAccount": {"id": refs["storage"]}},
            },
        ),
    )
    candidates: list[LinkRecord] = []
    selected = {
        "azure.resource-group-contains-resource",
        "azure.vm-nic-attached-to-vm",
        "azure.web-app-depends-on-storage",
    }
    for owner_key, row in rows:
        projected = project_provider_relationships(
            row,
            owner=resources[owner_key],
            arm_to_neutral=arm_to_neutral,
            catalog=catalog,
            arm_id_to_type=arm_id_to_type,
            to_neutral_id=to_neutral_id,
        )
        candidates.extend(
            link
            for link in projected.links
            if link.mapping_evidence is not None and link.mapping_evidence.mapping_id in selected
        )

    result = _verify(
        resources=tuple(resources.values()),
        links=tuple(candidates),
    )

    assert {
        (
            link.from_id,
            link.link_type,
            link.to_id,
        )
        for link in result.links
    } == {
        (
            resources["group"].resource_id,
            "contains",
            resources["vm"].resource_id,
        ),
        (
            resources["group"].resource_id,
            "contains",
            resources["web"].resource_id,
        ),
        (
            resources["nic"].resource_id,
            "attached_to",
            resources["vm"].resource_id,
        ),
        (
            resources["web"].resource_id,
            "depends_on",
            resources["storage"].resource_id,
        ),
    }


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
    assert result.dropped[0].source_provider_type == "Microsoft.Compute/virtualMachines"
    assert result.dropped[0].target_provider_type == "Microsoft.Network/networkInterfaces"
    assert result.dropped[0].unavailable_reason is (
        RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION
    )


def test_target_type_mismatch_is_absent_and_reported() -> None:
    result = _verify(
        resources=(
            _resource("nic-1", "network.interface"),
            _resource("vm-1", "compute.container-app"),
        )
    )

    assert result.links == ()
    assert [drop.reason for drop in result.dropped] == [RelationshipDropReason.TARGET_TYPE_MISMATCH]
    assert result.dropped[0].unavailable_reason is (
        RelationshipUnavailableReason.TARGET_PROVIDER_TYPE_UNMODELED
    )


def test_distinct_missing_target_candidates_keep_their_counts() -> None:
    result = _verify(
        resources=(
            _resource("nic-1", "network.interface"),
            _resource("nic-2", "network.interface"),
        ),
        links=(
            _link(to_id="missing-vm-1"),
            _link(from_id="nic-2", to_id="missing-vm-2"),
        ),
    )

    assert [drop.reason for drop in result.dropped] == [
        RelationshipDropReason.MISSING_TARGET_ENDPOINT,
        RelationshipDropReason.MISSING_TARGET_ENDPOINT,
    ]


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


def test_repeated_identical_resource_observation_does_not_break_verification() -> None:
    result = _verify(
        resources=(
            _resource("nic-1", "network.interface"),
            _resource("vm-1", "compute.vm"),
            replace(_resource("vm-1", "compute.vm"), last_seen="2026-08-12T11:59:30Z"),
        ),
    )

    assert result.dropped == ()
    assert len(result.links) == 1
    metadata = result.links[0].observation_metadata
    assert metadata is not None
    assert metadata.state_fact.effective_at == datetime(2026, 8, 12, 11, 59, tzinfo=UTC)


def test_contested_endpoint_observation_is_never_certified_as_verified() -> None:
    result = _verify(
        resources=(
            _resource("nic-1", "network.interface"),
            _resource("vm-1", "compute.vm"),
            replace(_resource("vm-1", "compute.vm"), props={"status": "deallocated"}),
        ),
    )

    assert result.links == ()
    assert [item.reason for item in result.dropped] == [RelationshipDropReason.UNVERIFIED_METADATA]
