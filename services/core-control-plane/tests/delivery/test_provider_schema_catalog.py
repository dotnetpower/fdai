"""Integrity and global-accounting checks for the shipped provider schema baseline."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from fdai.delivery.azure.provider_relationship_schema import (
    AzureArmIdReference,
    AzureProviderRelationshipSchemaSnapshot,
    AzureResourceDefinitionEvidence,
)
from fdai.delivery.provider_schema import (
    ProviderSchemaCoverageStatus,
    provider_schema_snapshot_from_mapping,
)
from fdai.delivery.provider_schema_relationship_review import (
    ProviderSchemaRelationshipReview,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    load_provider_relationship_mapping_catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_ROOT = REPO_ROOT / "provider-schema-catalog"


def test_shipped_global_catalog_is_complete_content_addressed_and_authority_free() -> None:
    index = _mapping(CATALOG_ROOT / "index.json")
    snapshot_digest = str(index["snapshot_digest"])
    coverage_digest = str(index["coverage_digest"])
    snapshot_path = (
        CATALOG_ROOT / "azure" / "snapshots" / f"{snapshot_digest.removeprefix('sha256:')}.json.gz"
    )
    coverage_path = (
        CATALOG_ROOT / "azure" / "coverage" / f"{coverage_digest.removeprefix('sha256:')}.json"
    )

    snapshot = provider_schema_snapshot_from_mapping(_mapping(snapshot_path))
    coverage = _mapping(coverage_path)
    canonical_coverage = json.dumps(
        coverage,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert snapshot.schema_digest == snapshot_digest
    assert "sha256:" + hashlib.sha256(canonical_coverage).hexdigest() == coverage_digest
    assert index["complete"] is True
    assert index["grants_authority"] is False
    assert snapshot.to_mapping()["grants_authority"] is False
    assert coverage["grants_authority"] is False
    assert len(snapshot.types) == index["type_count"]
    assert len(snapshot.types) >= 3_405


def test_shipped_coverage_accounts_for_every_type_with_terminal_disposition() -> None:
    index = _mapping(CATALOG_ROOT / "index.json")
    snapshot_digest = str(index["snapshot_digest"])
    coverage_digest = str(index["coverage_digest"])
    snapshot = provider_schema_snapshot_from_mapping(
        _mapping(
            CATALOG_ROOT
            / "azure"
            / "snapshots"
            / f"{snapshot_digest.removeprefix('sha256:')}.json.gz"
        )
    )
    coverage = _mapping(
        CATALOG_ROOT / "azure" / "coverage" / f"{coverage_digest.removeprefix('sha256:')}.json"
    )
    entries = coverage["entries"]
    assert isinstance(entries, list)
    snapshot_types = {item.resource_type for item in snapshot.types}
    covered_types = {str(entry["resource_type"]) for entry in entries if isinstance(entry, dict)}
    statuses = {str(entry["status"]) for entry in entries if isinstance(entry, dict)}

    assert covered_types == snapshot_types
    assert len(covered_types) == len(entries)
    assert statuses == {status.value for status in ProviderSchemaCoverageStatus}
    assert coverage["type_count"] == len(snapshot.types)
    assert coverage["modeled_count"] == index["modeled_count"]
    assert sum(coverage["status_counts"].values()) == len(snapshot.types)


def test_shipped_relationship_evidence_is_pinned_complete_and_authority_free() -> None:
    index = _mapping(CATALOG_ROOT / "index.json")
    evidence_digest = str(index["relationship_evidence_digest"])
    evidence = _mapping(
        CATALOG_ROOT
        / "azure"
        / "relationships"
        / f"{evidence_digest.removeprefix('sha256:')}.json.gz"
    )
    material = {
        key: evidence[key]
        for key in (
            "schema_version",
            "provider",
            "source_kind",
            "source_revision",
            "provider_schema_digest",
            "extension_document_count",
            "arm_id_references",
            "resource_definitions",
        )
    }
    canonical = json.dumps(
        material,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    references = evidence["arm_id_references"]
    definitions = evidence["resource_definitions"]
    assert isinstance(references, list)
    assert isinstance(definitions, list)
    exact = sum(isinstance(item, dict) and item.get("resolution") == "exact" for item in references)
    unresolved = sum(
        isinstance(item, dict) and item.get("resolution") == "unresolved" for item in references
    )

    assert "sha256:" + hashlib.sha256(canonical).hexdigest() == evidence_digest
    assert evidence["evidence_digest"] == evidence_digest
    assert evidence["provider_schema_digest"] == index["snapshot_digest"]
    assert evidence["source_revision"] == index["relationship_source"]["revision"]
    assert evidence["extension_document_count"] == index["relationship_extension_document_count"]
    assert len(references) == index["arm_id_reference_count"]
    assert exact == index["exact_arm_id_reference_count"]
    assert unresolved == index["unresolved_arm_id_reference_count"]
    assert exact + unresolved == len(references)
    assert len(definitions) == index["azure_resource_definition_count"]
    assert evidence["grants_authority"] is False


def test_shipped_relationship_review_is_replay_identical_and_authority_free() -> None:
    index = _mapping(CATALOG_ROOT / "index.json")
    relationship_digest = str(index["relationship_evidence_digest"])
    relationship = _mapping(
        CATALOG_ROOT
        / "azure/relationships"
        / f"{relationship_digest.removeprefix('sha256:')}.json.gz"
    )
    coverage_digest = str(index["coverage_digest"])
    coverage = _mapping(
        CATALOG_ROOT / "azure/coverage" / f"{coverage_digest.removeprefix('sha256:')}.json"
    )
    review_digest = str(index["relationship_review_digest"])
    shipped = _mapping(
        CATALOG_ROOT / "azure/reviews" / f"{review_digest.removeprefix('sha256:')}.json.gz"
    )

    snapshot = _relationship_snapshot(relationship)
    assert snapshot.evidence_digest == relationship_digest
    modeled = frozenset(
        str(entry["resource_type"])
        for entry in coverage["entries"]
        if isinstance(entry, dict) and entry.get("status") == "modeled"
    )
    mapping_catalog = load_provider_relationship_mapping_catalog(
        REPO_ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    rebuilt = ProviderSchemaRelationshipReview.build(
        relationship_snapshot=snapshot,
        modeled_provider_types=modeled,
        mapping_catalog=mapping_catalog,
    ).to_mapping()

    assert rebuilt == shipped
    assert shipped["review_digest"] == review_digest
    assert shipped["exact_reference_count"] == 4_707
    assert shipped["missing_source_reference_count"] == 471
    assert shipped["target_only_type_count"] == 94
    assert shipped["unique_endpoint_pair_count"] == 908
    assert shipped["endpoint_coverage_counts"] == {
        "both_modeled": 46,
        "neither_modeled": 593,
        "source_only_modeled": 56,
        "target_only_modeled": 213,
    }
    assert shipped["reviewed_mapping_overlap_count"] == 7
    assert shipped["semantic_review_status"] == "review_required"
    assert shipped["automatic_promotion"] is False
    assert shipped["grants_authority"] is False
    assert index["relationship_candidate_pair_count"] == shipped["unique_endpoint_pair_count"]
    assert (
        index["relationship_missing_source_reference_count"]
        == shipped["missing_source_reference_count"]
    )
    assert index["relationship_target_only_type_count"] == shipped["target_only_type_count"]
    assert (
        index["relationship_reviewed_mapping_overlap_count"]
        == shipped["reviewed_mapping_overlap_count"]
    )
    assert index["relationship_semantic_review_status"] == shipped["semantic_review_status"]
    assert index["relationship_automatic_promotion"] is shipped["automatic_promotion"]
    serialized = json.dumps(shipped, sort_keys=True)
    assert "link_type" not in serialized
    assert "endpoint_orientation" not in serialized


def _relationship_snapshot(raw: dict[str, object]) -> AzureProviderRelationshipSchemaSnapshot:
    references = raw["arm_id_references"]
    definitions = raw["resource_definitions"]
    assert isinstance(references, list)
    assert isinstance(definitions, list)
    return AzureProviderRelationshipSchemaSnapshot.build(
        source_revision=str(raw["source_revision"]),
        provider_schema_digest=str(raw["provider_schema_digest"]),
        extension_document_count=int(str(raw["extension_document_count"])),
        arm_id_references=tuple(
            AzureArmIdReference(
                source_document=str(item["source_document"]),
                json_pointer=str(item["json_pointer"]),
                allowed_resource_types=tuple(
                    str(value) for value in item["allowed_resource_types"]
                ),
                unresolved_allowed_resources=tuple(
                    str(value) for value in item["unresolved_allowed_resources"]
                ),
                operation_paths=tuple(str(value) for value in item["operation_paths"]),
                source_resource_types=tuple(str(value) for value in item["source_resource_types"]),
            )
            for item in references
            if isinstance(item, dict)
        ),
        resource_definitions=tuple(
            AzureResourceDefinitionEvidence(
                source_document=str(item["source_document"]),
                json_pointer=str(item["json_pointer"]),
                operation_paths=tuple(str(value) for value in item["operation_paths"]),
                source_resource_types=tuple(str(value) for value in item["source_resource_types"]),
            )
            for item in definitions
            if isinstance(item, dict)
        ),
    )


def _mapping(path: Path) -> dict[str, object]:
    payload = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    raw = json.loads(payload)
    assert isinstance(raw, dict)
    return raw
