"""Adversarial tests for versioned provider relationship materialization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.delivery.azure.provider_relationship_schema import (
    AzureArmIdReference,
    AzureProviderRelationshipSchemaSnapshot,
)
from fdai.delivery.provider_schema import ProviderSchemaSnapshot, ProviderSchemaType
from fdai.delivery.provider_schema_relationship_generation import (
    ProviderSchemaRelationshipCandidate,
    RelationshipGenerationDropReason,
    RelationshipLinkMetadata,
    changed_provider_type_versions,
    generate_provider_schema_relationship_generation,
    invalidate_changed_relationship_candidates,
    replay_provider_schema_relationship_generation,
    transitive_changed_provider_types,
)
from fdai.delivery.provider_schema_relationship_ledger import ProviderSchemaRelationshipLedger
from fdai.delivery.provider_schema_relationship_review import ProviderSchemaRelationshipReview
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
    load_provider_relationship_mapping_catalog,
)

ROOT = Path(__file__).resolve().parents[4]
SCHEMA_DIGEST = "sha256:" + "a" * 64
ARG_SCHEMA_DIGEST = "sha256:86b6fc0038f0492047c287e9bfc3c694ea9192658848ebdabee85ad4f8cb1340"
MANIFEST_DIGEST = "sha256:" + "b" * 64


def _schema(
    *,
    version: str = "2026-01-01",
    preview: tuple[str, ...] = (),
    revision: str = "c" * 40,
) -> ProviderSchemaSnapshot:
    return ProviderSchemaSnapshot.build(
        provider="azure",
        source_revision=revision,
        types=(
            ProviderSchemaType(
                resource_type="Microsoft.Web/serverFarms",
                stable_api_versions=(version,),
                preview_api_versions=preview,
                preferred_api_version=version,
                source_document="generated/web/types.md",
            ),
            ProviderSchemaType(
                resource_type="Microsoft.Web/sites",
                stable_api_versions=(version,),
                preview_api_versions=preview,
                preferred_api_version=version,
                source_document="generated/web/types.md",
            ),
        ),
    )


def _review(
    schema: ProviderSchemaSnapshot,
) -> tuple[AzureProviderRelationshipSchemaSnapshot, ProviderSchemaRelationshipReview]:
    evidence = AzureProviderRelationshipSchemaSnapshot.build(
        source_revision="d" * 40,
        provider_schema_digest=schema.schema_digest,
        extension_document_count=1,
        arm_id_references=(
            AzureArmIdReference(
                source_document="specification/web/resource-manager/web.json",
                json_pointer="/definitions/Site/properties/serverFarmId",
                allowed_resource_types=("microsoft.web/serverfarms",),
                unresolved_allowed_resources=(),
                operation_paths=("/providers/Microsoft.Web/sites/{name}",),
                source_resource_types=("microsoft.web/sites",),
            ),
        ),
        resource_definitions=(),
    )
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    return evidence, ProviderSchemaRelationshipReview.build(
        relationship_snapshot=evidence,
        modeled_provider_types=frozenset({"microsoft.web/sites", "microsoft.web/serverfarms"}),
        mapping_catalog=catalog,
    )


def _metadata() -> RelationshipLinkMetadata:
    return RelationshipLinkMetadata(
        mapping_id="azure.function-depends-on-app-service-plan",
        source_provider_type="microsoft.web/sites",
        target_provider_type="microsoft.web/serverfarms",
        link_type="depends_on",
        endpoint_orientation=EndpointOrientation.OWNER_TO_REFERENCED,
        cardinality="many_to_many",
        source_property_path="properties.serverFarmId",
        source_schema_version="azure-resource-graph-resources@2022-10-01",
        source_schema_digest=ARG_SCHEMA_DIGEST,
        projection_manifest_digest=MANIFEST_DIGEST,
    )


def _generation(
    schema: ProviderSchemaSnapshot,
    *,
    metadata: dict[str, RelationshipLinkMetadata] | None = None,
):
    evidence, review = _review(schema)
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    return generate_provider_schema_relationship_generation(
        provider_schema=schema,
        relationship_snapshot=evidence,
        review=review,
        mapping_catalog=catalog,
        link_metadata={} if metadata is None else metadata,
        generation_ref="provider-schema-generation:one",
        projection_manifest_digest=MANIFEST_DIGEST,
    )


def test_missing_link_metadata_is_inert_and_incomplete() -> None:
    generation = _generation(_schema())

    assert generation.candidates == ()
    assert generation.complete is False
    assert generation.drops == (RelationshipGenerationDropReason.MISSING_LINK_METADATA,)
    assert generation.semantic_promotion == "proposal_only"
    assert generation.graph_mutation_authority is False
    assert generation.migration_execution_authority is False


def test_materialization_binds_direction_cardinality_and_manifest() -> None:
    generation = _generation(
        _schema(),
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )

    candidate = generation.candidates[0]
    assert candidate.metadata.endpoint_orientation is EndpointOrientation.OWNER_TO_REFERENCED
    assert candidate.metadata.cardinality == "many_to_many"
    assert candidate.metadata.projection_manifest_digest == MANIFEST_DIGEST
    assert candidate.source_provider_versions == ("2026-01-01",)
    assert candidate.target_provider_versions == ("2026-01-01",)
    assert generation.complete is True


def test_candidate_versions_are_a_globally_sorted_unique_union() -> None:
    generation = _generation(
        _schema(preview=("2025-12-01-preview",)),
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )

    candidate = generation.candidates[0]
    assert candidate.source_provider_versions == ("2025-12-01-preview", "2026-01-01")
    assert candidate.target_provider_versions == ("2025-12-01-preview", "2026-01-01")


def test_unresolved_and_sourceless_references_make_generation_incomplete() -> None:
    schema = _schema()
    evidence = AzureProviderRelationshipSchemaSnapshot.build(
        source_revision="d" * 40,
        provider_schema_digest=schema.schema_digest,
        extension_document_count=1,
        arm_id_references=(
            AzureArmIdReference(
                source_document="specification/web/resource-manager/web.json",
                json_pointer="/definitions/Site/properties/serverFarmId",
                allowed_resource_types=(),
                unresolved_allowed_resources=("unknown",),
                operation_paths=(),
                source_resource_types=("microsoft.web/sites",),
            ),
            AzureArmIdReference(
                source_document="specification/web/resource-manager/web.json",
                json_pointer="/definitions/Reference/properties/id",
                allowed_resource_types=("microsoft.web/serverfarms",),
                unresolved_allowed_resources=(),
                operation_paths=(),
                source_resource_types=(),
            ),
        ),
        resource_definitions=(),
    )
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    review = ProviderSchemaRelationshipReview.build(
        relationship_snapshot=evidence,
        modeled_provider_types=frozenset({"microsoft.web/sites", "microsoft.web/serverfarms"}),
        mapping_catalog=catalog,
    )

    generation = generate_provider_schema_relationship_generation(
        provider_schema=schema,
        relationship_snapshot=evidence,
        review=review,
        mapping_catalog=catalog,
        link_metadata={},
        generation_ref="provider-schema-generation:one",
        projection_manifest_digest=MANIFEST_DIGEST,
    )

    assert generation.complete is False
    assert generation.drops == (
        RelationshipGenerationDropReason.SOURCELESS_REFERENCE,
        RelationshipGenerationDropReason.UNRESOLVED_REFERENCE,
    )


def test_semantic_mapping_fields_are_verified_against_the_reviewed_catalog() -> None:
    for field, value in (("link_type", "attached_to"), ("cardinality", "one_to_many")):
        metadata = replace(_metadata(), **{field: value})
        generation = _generation(
            _schema(),
            metadata={"azure.function-depends-on-app-service-plan": metadata},
        )

        assert generation.candidates == ()
        assert generation.complete is False
        assert generation.drops == (RelationshipGenerationDropReason.STALE_LINK_METADATA,)


def test_review_digest_is_recomputed_before_materialization() -> None:
    schema = _schema()
    evidence, review = _review(schema)
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    object.__setattr__(review, "review_digest", "sha256:" + "f" * 64)

    with pytest.raises(ValueError, match="review digest mismatch"):
        generate_provider_schema_relationship_generation(
            provider_schema=schema,
            relationship_snapshot=evidence,
            review=review,
            mapping_catalog=catalog,
            link_metadata={"azure.function-depends-on-app-service-plan": _metadata()},
            generation_ref="provider-schema-generation:one",
            projection_manifest_digest=MANIFEST_DIGEST,
        )


def test_conflicting_duplicate_metadata_is_not_order_dependent() -> None:
    schema = _schema()
    evidence, review = _review(schema)
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    conflicting = RelationshipLinkMetadata(
        mapping_id="azure.function-depends-on-app-service-plan",
        source_provider_type="microsoft.web/sites",
        target_provider_type="microsoft.web/serverfarms",
        link_type="depends_on",
        endpoint_orientation=EndpointOrientation.REFERENCED_TO_OWNER,
        cardinality="many_to_many",
        source_property_path="properties.serverFarmId",
        source_schema_version="azure-resource-graph-resources@2022-10-01",
        source_schema_digest=ARG_SCHEMA_DIGEST,
        projection_manifest_digest=MANIFEST_DIGEST,
    )
    generation = generate_provider_schema_relationship_generation(
        provider_schema=schema,
        relationship_snapshot=evidence,
        review=review,
        mapping_catalog=catalog,
        link_metadata={"z": _metadata(), "a": conflicting},
        generation_ref="provider-schema-generation:one",
        projection_manifest_digest=MANIFEST_DIGEST,
    )
    assert generation.candidates == ()
    assert generation.drops == (RelationshipGenerationDropReason.AMBIGUOUS_LINK_METADATA,)


def test_stale_relationship_evidence_release_is_rejected() -> None:
    schema = _schema()
    evidence, review = _review(schema)
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    with pytest.raises(ValueError, match="schema release is stale"):
        generate_provider_schema_relationship_generation(
            provider_schema=_schema(revision="e" * 40),
            relationship_snapshot=evidence,
            review=review,
            mapping_catalog=catalog,
            link_metadata={"mapping": _metadata()},
            generation_ref="generation",
            projection_manifest_digest=MANIFEST_DIGEST,
        )


def test_changed_subset_invalidation_does_not_reuse_unrelated_candidates() -> None:
    baseline = _schema()
    observed = _schema(version="2026-02-01", revision="e" * 40)
    changed = changed_provider_type_versions(baseline, observed)
    assert "microsoft.web/sites" in changed
    generation = _generation(
        baseline,
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )
    invalidated = invalidate_changed_relationship_candidates(generation, changed)
    assert invalidated.candidates == ()
    assert invalidated.complete is False
    assert RelationshipGenerationDropReason.STALE_LINK_METADATA in invalidated.drops


def test_incremental_invalidation_expands_only_through_transitive_references() -> None:
    generation = _generation(
        _schema(),
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )
    first = generation.candidates[0]

    def candidate(
        source: str,
        target: str,
        mapping_id: str,
    ) -> ProviderSchemaRelationshipCandidate:
        return replace(
            first,
            source_provider_type=source,
            target_provider_type=target,
            metadata=replace(
                first.metadata,
                mapping_id=mapping_id,
                source_provider_type=source,
                target_provider_type=target,
            ),
        )

    candidates = tuple(
        sorted(
            (
                candidate("microsoft.example/a", "microsoft.example/b", "mapping-a-b"),
                candidate("microsoft.example/b", "microsoft.example/c", "mapping-b-c"),
                candidate("microsoft.example/x", "microsoft.example/y", "mapping-x-y"),
            ),
            key=lambda item: (
                item.source_provider_type,
                item.target_provider_type,
                item.metadata.mapping_id,
            ),
        )
    )
    expanded_generation = replace(generation, candidates=candidates)

    changed = transitive_changed_provider_types(
        expanded_generation,
        ("microsoft.example/c@2026-01-01",),
    )
    invalidated = invalidate_changed_relationship_candidates(
        expanded_generation,
        ("microsoft.example/c@2026-01-01",),
    )

    assert changed == frozenset(
        {
            "microsoft.example/a",
            "microsoft.example/b",
            "microsoft.example/c",
            "microsoft.example/c@2026-01-01",
        }
    )
    assert [candidate.metadata.mapping_id for candidate in invalidated.candidates] == [
        "mapping-x-y"
    ]


def test_ledger_rollback_keeps_proposal_only_authority(tmp_path: Path) -> None:
    first = _generation(
        _schema(),
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )
    second = _generation(
        _schema(version="2026-02-01", revision="e" * 40),
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )
    ledger = ProviderSchemaRelationshipLedger(tmp_path)
    ledger.record(first)
    ledger.record(second)
    assert ledger.rollback(first.generation_digest) == first.generation_digest
    active = ledger.read_active()
    assert active == {
        "generation_digest": first.generation_digest,
        "graph_mutation_authority": False,
        "migration_execution_authority": False,
        "semantic_promotion": "proposal_only",
    }

    evidence, review = _review(_schema())
    catalog = load_provider_relationship_mapping_catalog(
        ROOT / "rule-catalog/vocabulary/provider-relationship-mappings"
    )
    assert replay_provider_schema_relationship_generation(
        first,
        provider_schema=_schema(),
        relationship_snapshot=evidence,
        review=review,
        mapping_catalog=catalog,
        link_metadata={"azure.function-depends-on-app-service-plan": _metadata()},
        generation_ref="provider-schema-generation:one",
        projection_manifest_digest=MANIFEST_DIGEST,
    )


def test_ledger_serializes_concurrent_recorders_with_unique_staging_files(
    tmp_path: Path,
) -> None:
    generation = _generation(
        _schema(),
        metadata={"azure.function-depends-on-app-service-plan": _metadata()},
    )
    ledger = ProviderSchemaRelationshipLedger(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as workers:
        digests = tuple(workers.map(lambda _: ledger.record(generation), range(32)))

    assert set(digests) == {generation.generation_digest}
    assert ledger.read_active() is not None


def test_direction_shadow_exact_release_rejects_mixed_provider_schema() -> None:
    from fdai.core.ontology_platform.direction_shadow import (
        ComparisonDisposition,
        DirectionGraphGeneration,
        RebuildPointer,
        ReviewReason,
        compare_exact_release_graph_generations,
        replay_matches,
    )

    kwargs = {
        "generation_ref": "generation",
        "ontology_release_digest": SCHEMA_DIGEST,
        "object_ids": (),
        "links": (),
        "complete": True,
        "mapping_revision": "mapping-a",
    }
    legacy = DirectionGraphGeneration.create(provider_schema_digest=SCHEMA_DIGEST, **kwargs)
    aligned = DirectionGraphGeneration.create(
        provider_schema_digest="sha256:" + "c" * 64,
        **kwargs,
    )
    receipt = compare_exact_release_graph_generations(
        legacy,
        aligned,
        migration_revision="migration",
        rebuild_pointer=RebuildPointer(
            authoritative_generation_ref="inventory-generation",
            rebuild_procedure_ref="runbook:rebuild",
        ),
    )
    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED
    assert ReviewReason.PROVIDER_SCHEMA_RELEASE_MISMATCH in receipt.review_reasons
    assert receipt.exact_release_mode is True
    assert replay_matches(receipt, legacy, aligned) is True


def test_direction_shadow_exact_release_requires_both_mapping_revisions() -> None:
    from fdai.core.ontology_platform.direction_shadow import (
        ComparisonDisposition,
        DirectionGraphGeneration,
        RebuildPointer,
        ReviewReason,
        compare_exact_release_graph_generations,
    )

    kwargs = {
        "generation_ref": "generation",
        "ontology_release_digest": SCHEMA_DIGEST,
        "object_ids": (),
        "links": (),
        "complete": True,
    }
    legacy = DirectionGraphGeneration.create(
        provider_schema_digest=SCHEMA_DIGEST,
        mapping_revision="mapping-a",
        **kwargs,
    )
    aligned = DirectionGraphGeneration.create(provider_schema_digest=SCHEMA_DIGEST, **kwargs)
    receipt = compare_exact_release_graph_generations(
        legacy,
        aligned,
        migration_revision="migration",
        rebuild_pointer=RebuildPointer(
            authoritative_generation_ref="inventory-generation",
            rebuild_procedure_ref="runbook:rebuild",
        ),
    )
    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED
    assert ReviewReason.ALIGNED_MAPPING_RELEASE_UNBOUND in receipt.review_reasons
