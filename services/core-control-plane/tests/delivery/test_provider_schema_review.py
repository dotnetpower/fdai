"""Provider schema review validation and Heimdall drift projection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.azure.provider_relationship_schema import (
    AzureArmIdReference,
    AzureProviderRelationshipSchemaSnapshot,
)
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_relationship_review import (
    ProviderSchemaRelationshipReview,
)
from fdai.delivery.provider_schema_review import (
    provider_schema_drift_payload,
    validate_provider_schema_review_package,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _package() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "provider-schema-drift-review",
        "provider": "azure",
        "source_revision": "a" * 40,
        "baseline_digest": "sha256:" + "1" * 64,
        "observed_digest": "sha256:" + "2" * 64,
        "drift_digest": "3" * 64,
        "drift_kind": "breaking",
        "added_types": ["microsoft.example/new"],
        "removed_types": ["microsoft.example/old"],
        "added_stable_versions": [],
        "removed_stable_versions": ["microsoft.example/widgets@2024-01-01"],
        "added_preview_versions": [],
        "removed_preview_versions": [],
        "type_count": 10,
        "modeled_count": 2,
        "coverage_status_counts": {"modeled": 2, "unsupported-with-reason": 8},
        "review_required": True,
        "grants_authority": False,
    }


def test_projects_digest_bound_shadow_drift_without_raw_schema() -> None:
    first = provider_schema_drift_payload(_package())
    second = provider_schema_drift_payload(_package())

    assert first == second
    assert first["producer_principal"] == "Heimdall"
    assert first["event_type"] == "provider.schema_drift"
    assert first["authority_ceiling"] == "shadow"
    assert first["review_required"] is True
    assert first["grants_authority"] is False
    assert first["added_type_count"] == 1
    assert "added_types" not in first


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("drift_kind", "unchanged", "MUST NOT create"),
        ("review_required", False, "authority boundary"),
        ("grants_authority", True, "authority boundary"),
        ("removed_types", [], "no stable removal"),
        ("coverage_status_counts", {"modeled": 2}, "incomplete"),
    ],
)
def test_rejects_unsafe_or_incomplete_review_packages(
    field: str,
    value: object,
    message: str,
) -> None:
    package = _package()
    package[field] = value
    if field == "removed_types":
        package["removed_stable_versions"] = []

    with pytest.raises(ProviderSchemaError, match=message):
        validate_provider_schema_review_package(package)


def test_rejects_extra_untrusted_fields() -> None:
    package = _package()
    package["raw_schema"] = {"secret": "not allowed"}

    with pytest.raises(ProviderSchemaError, match="fields are invalid"):
        validate_provider_schema_review_package(package)


def test_classifies_exact_pairs_without_inventing_semantics_or_authority() -> None:
    snapshot = AzureProviderRelationshipSchemaSnapshot.build(
        source_revision="a" * 40,
        provider_schema_digest="sha256:" + "b" * 64,
        extension_document_count=2,
        arm_id_references=(
            AzureArmIdReference(
                source_document="specification/web/resource-manager/web.json",
                json_pointer="/definitions/SiteConfig/properties/serverFarmId",
                allowed_resource_types=("microsoft.web/serverfarms",),
                unresolved_allowed_resources=(),
                operation_paths=("/providers/Microsoft.Web/sites/{name}",),
                source_resource_types=("microsoft.web/sites",),
            ),
            AzureArmIdReference(
                source_document="specification/common/resource-manager/common.json",
                json_pointer="/definitions/Target/properties/id",
                allowed_resource_types=("microsoft.storage/storageaccounts",),
                unresolved_allowed_resources=(),
                operation_paths=(),
                source_resource_types=(),
            ),
        ),
        resource_definitions=(),
    )
    catalog = load_provider_relationship_mapping_catalog(
        REPO_ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )

    first = ProviderSchemaRelationshipReview.build(
        relationship_snapshot=snapshot,
        modeled_provider_types=frozenset({"microsoft.web/sites", "microsoft.web/serverfarms"}),
        mapping_catalog=catalog,
    )
    second = ProviderSchemaRelationshipReview.build(
        relationship_snapshot=snapshot,
        modeled_provider_types=frozenset({"microsoft.web/sites", "microsoft.web/serverfarms"}),
        mapping_catalog=catalog,
    )

    assert first == second
    payload = first.to_mapping()
    assert payload["exact_reference_count"] == 2
    assert payload["missing_source_reference_count"] == 1
    assert payload["target_only_type_count"] == 1
    assert payload["unique_endpoint_pair_count"] == 1
    assert payload["endpoint_coverage_counts"] == {"both_modeled": 1}
    assert payload["reviewed_mapping_overlap_ids"] == ["azure.function-depends-on-app-service-plan"]
    assert payload["semantic_review_status"] == "review_required"
    assert payload["automatic_promotion"] is False
    assert payload["grants_authority"] is False
    serialized = json.dumps(payload, sort_keys=True)
    assert "link_type" not in serialized
    assert "endpoint_orientation" not in serialized
