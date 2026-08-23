"""Contract tests for reviewed provider relationship mappings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
    ProviderReferenceFormat,
    ProviderRelationshipMappingCatalogError,
    load_provider_relationship_mapping_catalog,
    provider_relationship_mapping_content_hash,
)

CATALOG_ROOT = Path("rule-catalog/vocabulary/provider-relationship-mappings")


def _catalog() -> dict[str, Any]:
    catalog: dict[str, Any] = {
        "schema_version": "1.0.0",
        "mappings": [
            {
                "mapping_id": "azure.vm-network-interface",
                "provider": "azure",
                "source_identity": "azure-resource-graph",
                "source_provider_types": ["Microsoft.Compute/virtualMachines"],
                "source_property_path": "properties.networkProfile.networkInterfaces[].id",
                "target_provider_types": ["Microsoft.Network/networkInterfaces"],
                "link_type": "attached_to",
                "endpoint_orientation": "referenced_to_owner",
                "source_schema": {
                    "version": "arg-resources-2022-10-01",
                    "digest": "sha256:" + "1" * 64,
                },
                "evidence_method": "deterministic-cross-check",
                "freshness": {"max_age_seconds": 21600},
                "completeness": {
                    "require_complete_generation": True,
                    "require_source_endpoint": True,
                    "require_target_endpoint": True,
                },
            }
        ],
    }
    catalog["review"] = {
        "reviewer_identity": "fdai-provider-relationship-review",
        "reviewed_at": "2026-08-12T00:00:00Z",
        "immutable_receipt_ref": "catalog-receipt:provider-relationships:1.0.0",
        "content_hash": provider_relationship_mapping_content_hash(catalog),
    }
    return catalog


def _write(root: Path, catalog: dict[str, Any]) -> None:
    (root / "azure.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def test_loads_reviewed_provider_relationship_mapping(tmp_path: Path) -> None:
    catalog = _catalog()
    _write(tmp_path, catalog)

    loaded = load_provider_relationship_mapping_catalog(tmp_path)

    mapping = loaded.mappings[0]
    assert mapping.endpoint_orientation is EndpointOrientation.REFERENCED_TO_OWNER
    assert mapping.source_provider_types == ("microsoft.compute/virtualmachines",)
    assert mapping.target_provider_types == ("microsoft.network/networkinterfaces",)
    assert loaded.review.immutable_receipt_ref.startswith("catalog-receipt:")


def test_shipped_provider_catalog_is_reviewed_and_complete() -> None:
    loaded = load_provider_relationship_mapping_catalog(CATALOG_ROOT)

    assert len(loaded.mappings) >= 17
    assert {mapping.link_type for mapping in loaded.mappings} == {
        "attached_to",
        "contains",
        "depends_on",
        "kubernetes_exposes_endpoints",
        "kubernetes_selects",
        "peered_with",
        "routes_to",
    }
    assert all(mapping.completeness.require_complete_generation for mapping in loaded.mappings)


def test_shipped_catalog_declares_kubernetes_telemetry_relationship_direction() -> None:
    loaded = load_provider_relationship_mapping_catalog(CATALOG_ROOT)
    mappings = {mapping.mapping_id: mapping for mapping in loaded.mappings}

    selector = mappings["kubernetes.service-selects-pod"]
    assert selector.link_type == "kubernetes_selects"
    assert selector.endpoint_orientation is EndpointOrientation.OWNER_TO_REFERENCED
    assert selector.reference_format is ProviderReferenceFormat.LABEL_SELECTOR

    endpoints = mappings["kubernetes.service-exposes-endpoints"]
    assert endpoints.link_type == "kubernetes_exposes_endpoints"
    assert endpoints.endpoint_orientation is EndpointOrientation.OWNER_TO_REFERENCED
    assert endpoints.reference_format is ProviderReferenceFormat.RESOLVED_NAME


def test_shipped_relationship_mappings_match_canonical_endpoint_roles() -> None:
    loaded = load_provider_relationship_mapping_catalog(CATALOG_ROOT)
    assert len(loaded.mappings) == 75

    special_link_types = {
        "azure.vnet-peered-with-vnet": "peered_with",
        "kubernetes.service-exposes-endpoints": "kubernetes_exposes_endpoints",
        "kubernetes.service-selects-pod": "kubernetes_selects",
    }
    for mapping in loaded.mappings:
        expected_link_type = special_link_types.get(mapping.mapping_id)
        if expected_link_type is None:
            for token, link_type in (
                ("-attached-to-", "attached_to"),
                ("-depends-on-", "depends_on"),
                ("-routes-to-", "routes_to"),
                ("-contains-", "contains"),
            ):
                if token in mapping.mapping_id:
                    expected_link_type = link_type
                    break
        assert mapping.link_type == expected_link_type, mapping.mapping_id

    referenced_to_owner = {
        mapping.mapping_id
        for mapping in loaded.mappings
        if mapping.endpoint_orientation is EndpointOrientation.REFERENCED_TO_OWNER
    }
    assert referenced_to_owner == {
        "azure.private-endpoint-contains-dns-zone-group",
        "azure.private-dns-zone-contains-vnet-link",
        "azure.resource-group-contains-resource",
        "azure.sql-server-contains-database",
        "azure.vm-data-disk-attached-to-vm",
        "azure.vm-nic-attached-to-vm",
        "azure.vm-os-disk-attached-to-vm",
    }

    resolved_names = {
        mapping.mapping_id
        for mapping in loaded.mappings
        if mapping.reference_format is ProviderReferenceFormat.RESOLVED_NAME
    }
    assert resolved_names == {
        "azure.aks-attached-to-node-resource-group",
        "azure.application-gateway-routes-to-configured-backend",
        "azure.container-environment-depends-on-log-workspace",
        "azure.container-workload-depends-on-configured-endpoint",
        "azure.container-workload-depends-on-key-vault-secret",
        "azure.container-workload-depends-on-registry",
        "azure.role-assignment-attached-to-managed-identity",
        "azure.load-balancer-routes-to-configured-backend",
        "azure.web-app-depends-on-container-registry",
        "kubernetes.service-exposes-endpoints",
    }
    label_selectors = {
        mapping.mapping_id
        for mapping in loaded.mappings
        if mapping.reference_format is ProviderReferenceFormat.LABEL_SELECTOR
    }
    assert label_selectors == {"kubernetes.service-selects-pod"}


def test_rejects_stale_mapping_content_hash(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["mappings"][0]["source_property_path"] = "properties.changed.id"
    _write(tmp_path, catalog)

    with pytest.raises(ProviderRelationshipMappingCatalogError, match="content hash"):
        load_provider_relationship_mapping_catalog(tmp_path)


def test_rejects_ambiguous_endpoint_orientation(tmp_path: Path) -> None:
    catalog = _catalog()
    conflicting = dict(catalog["mappings"][0])
    conflicting["mapping_id"] = "azure.vm-network-interface-conflict"
    conflicting["endpoint_orientation"] = "owner_to_referenced"
    catalog["mappings"].append(conflicting)
    catalog["review"]["content_hash"] = provider_relationship_mapping_content_hash(catalog)
    _write(tmp_path, catalog)

    with pytest.raises(ProviderRelationshipMappingCatalogError, match="orientation is ambiguous"):
        load_provider_relationship_mapping_catalog(tmp_path)


def test_rejects_multiple_exact_parent_containment_mappings(tmp_path: Path) -> None:
    catalog = _catalog()
    first = catalog["mappings"][0]
    first.update(
        {
            "mapping_id": "azure.database-parent-one",
            "source_provider_types": ["Microsoft.Example/servers/databases"],
            "source_property_path": "id.providerParent",
            "target_provider_types": ["Microsoft.Example/servers"],
            "link_type": "contains",
            "endpoint_orientation": "referenced_to_owner",
        }
    )
    second = dict(first)
    second["mapping_id"] = "azure.database-parent-two"
    second["source_property_path"] = "properties.alternateParent.id"
    catalog["mappings"].append(second)
    catalog["review"]["content_hash"] = provider_relationship_mapping_content_hash(catalog)
    _write(tmp_path, catalog)

    with pytest.raises(
        ProviderRelationshipMappingCatalogError,
        match="parent containment is ambiguous",
    ):
        load_provider_relationship_mapping_catalog(tmp_path)


def test_rejects_untrusted_evidence_method(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["mappings"][0]["evidence_method"] = "provider-assertion"
    catalog["review"]["content_hash"] = provider_relationship_mapping_content_hash(catalog)
    _write(tmp_path, catalog)

    with pytest.raises(ProviderRelationshipMappingCatalogError, match="MUST be trusted"):
        load_provider_relationship_mapping_catalog(tmp_path)
