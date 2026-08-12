"""Contract tests for reviewed provider relationship mappings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
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


def test_shipped_azure_catalog_is_reviewed_and_complete() -> None:
    loaded = load_provider_relationship_mapping_catalog(CATALOG_ROOT)

    assert len(loaded.mappings) >= 15
    assert {mapping.link_type for mapping in loaded.mappings} == {
        "attached_to",
        "contains",
        "depends_on",
        "peered_with",
        "routes_to",
    }
    assert all(mapping.completeness.require_complete_generation for mapping in loaded.mappings)


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
