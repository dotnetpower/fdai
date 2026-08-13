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

    actual = {
        mapping.mapping_id: (
            mapping.link_type,
            mapping.endpoint_orientation,
            mapping.reference_format,
        )
        for mapping in loaded.mappings
    }

    assert actual == {
        "azure.diagnostic-setting-depends-on-workspace": (
            "depends_on",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.load-balancer-attached-to-public-ip": (
            "attached_to",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.nic-attached-to-subnet": (
            "attached_to",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.private-endpoint-attached-to-service": (
            "attached_to",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.resource-group-contains-resource": (
            "contains",
            EndpointOrientation.REFERENCED_TO_OWNER,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.route-table-routes-to-resource": (
            "routes_to",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.subnet-attached-to-nsg": (
            "attached_to",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.vm-data-disk-attached-to-vm": (
            "attached_to",
            EndpointOrientation.REFERENCED_TO_OWNER,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.vm-nic-attached-to-vm": (
            "attached_to",
            EndpointOrientation.REFERENCED_TO_OWNER,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.vm-os-disk-attached-to-vm": (
            "attached_to",
            EndpointOrientation.REFERENCED_TO_OWNER,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.vnet-contains-subnet": (
            "contains",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.vnet-peered-with-vnet": (
            "peered_with",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.web-app-attached-to-subnet": (
            "attached_to",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "azure.web-app-depends-on-container-registry": (
            "depends_on",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.RESOLVED_NAME,
        ),
        "azure.web-app-depends-on-storage": (
            "depends_on",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.ARM_ID,
        ),
        "kubernetes.service-exposes-endpoints": (
            "kubernetes_exposes_endpoints",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.RESOLVED_NAME,
        ),
        "kubernetes.service-selects-pod": (
            "kubernetes_selects",
            EndpointOrientation.OWNER_TO_REFERENCED,
            ProviderReferenceFormat.LABEL_SELECTOR,
        ),
    }


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


def test_rejects_untrusted_evidence_method(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["mappings"][0]["evidence_method"] = "provider-assertion"
    catalog["review"]["content_hash"] = provider_relationship_mapping_content_hash(catalog)
    _write(tmp_path, catalog)

    with pytest.raises(ProviderRelationshipMappingCatalogError, match="MUST be trusted"):
        load_provider_relationship_mapping_catalog(tmp_path)
