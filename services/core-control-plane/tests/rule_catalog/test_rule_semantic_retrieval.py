from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.rule_catalog.schema.rule_semantic_generation import (
    CatalogDocumentDigestChunk,
    CatalogDocumentDigestManifest,
    CatalogRetrievalReceipt,
    CatalogSearchGeneration,
    GenerationState,
    RetrievalOperation,
    RetrievalRank,
    SemanticAvailability,
    build_document_digest_manifest,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CohortMetric,
    RuleCorpus,
    RuleSemanticManifest,
    RuleSemanticSurface,
    SurfaceOrigin,
    SurfaceState,
    SurfaceValidationReceipt,
    ValidationDecision,
    query_digest,
)
from fdai.shared.contracts.models import Redistribution

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64
_C = "sha256:" + "c" * 64
_D = "sha256:" + "d" * 64


def _manifest() -> RuleSemanticManifest:
    return RuleSemanticManifest(
        rule_id="object-storage.public-access.deny",
        rule_version="1.0.0",
        corpus=RuleCorpus.ACTIVE,
        policy_ref="policies/object_storage/public_access.rego",
        policy_digest=_A,
        source_content_digest=_B,
        parser_id="opa-ast",
        parser_version="1.0.0",
        redistribution=Redistribution.EMBEDDABLE,
        resource_type="object-storage",
        ontology_release_digest=_C,
        signal_refs=("resource.configuration.observed",),
        property_refs=("property.object-storage.public_access",),
        action_type_ref="remediate.disable-public-access",
    )


def _surface(**overrides: object) -> RuleSemanticSurface:
    values: dict[str, object] = {
        "surface_id": "surface.object-storage.public-access.en",
        "manifest_digest": _manifest().digest,
        "locale": "en",
        "origin": SurfaceOrigin.GENERATED,
        "intent_ids": ("prevent-public-access",),
        "concept_refs": ("object-storage", "property.object-storage.public_access"),
        "aliases": ("block public blob access",),
        "training_queries": ("Which rule blocks public storage?",),
        "hard_negative_queries": ("Which rule enables storage versioning?",),
        "producer_ref": "model:semantic-enricher@1",
        "evidence_refs": ("rule:object-storage.public-access.deny@1.0.0",),
        "prompt_digest": _D,
    }
    values.update(overrides)
    return RuleSemanticSurface(**values)  # type: ignore[arg-type]


def test_manifest_identity_is_replay_stable() -> None:
    left = _manifest()
    right = _manifest()

    assert left.digest == right.digest
    assert left.corpus is RuleCorpus.ACTIVE


def test_semantic_surface_cannot_gain_execution_authority() -> None:
    with pytest.raises(ValueError, match="execution authority"):
        _surface(execution_authority=True)


def test_generated_surface_requires_prompt_evidence() -> None:
    with pytest.raises(ValueError, match="prompt_digest"):
        _surface(prompt_digest=None)


def test_surface_promotion_requires_validation_receipt() -> None:
    with pytest.raises(ValueError, match="validation evidence"):
        _surface(state=SurfaceState.PROMOTED)


def test_surface_rejects_training_and_negative_overlap() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        _surface(hard_negative_queries=(" which RULE blocks PUBLIC storage? ",))


def test_held_out_validation_rejects_training_leakage() -> None:
    with pytest.raises(ValueError, match="held-out"):
        SurfaceValidationReceipt(
            surface_digest=_A,
            dataset_digest=_B,
            evaluator_ref="heimdall:rule-retrieval@1",
            training_query_digests=(_C,),
            evaluation_query_digests=(_C,),
            cohort_metrics=(CohortMetric("en", "recall-at-5", 1.0, 1),),
            failure_codes=(),
            decision=ValidationDecision.PASS,
        )


def test_passing_validation_cannot_hide_failures() -> None:
    with pytest.raises(ValueError, match="MUST NOT carry failures"):
        SurfaceValidationReceipt(
            surface_digest=_A,
            dataset_digest=_B,
            evaluator_ref="heimdall:rule-retrieval@1",
            training_query_digests=(_C,),
            evaluation_query_digests=(_D,),
            cohort_metrics=(CohortMetric("en", "recall-at-5", 0.5, 2),),
            failure_codes=("target-not-retrieved",),
            decision=ValidationDecision.PASS,
        )


def test_active_generation_requires_validation_and_aware_activation() -> None:
    with pytest.raises(ValueError, match="validation and activation"):
        CatalogSearchGeneration(
            generation_id="active-1",
            corpus=RuleCorpus.ACTIVE,
            catalog_digest=_A,
            semantic_schema_digest=_B,
            ontology_release_digest=_C,
            embedding_space_id="catalog-search-384",
            embedding_model_version="embedding:1",
            embedding_dimension=384,
            document_digests=(_D,),
            state=GenerationState.ACTIVE,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        CatalogSearchGeneration(
            generation_id="active-1",
            corpus=RuleCorpus.ACTIVE,
            catalog_digest=_A,
            semantic_schema_digest=_B,
            ontology_release_digest=_C,
            embedding_space_id="catalog-search-384",
            embedding_model_version="embedding:1",
            embedding_dimension=384,
            document_digests=(_D,),
            state=GenerationState.ACTIVE,
            validation_receipt_digest=_A,
            activated_at=datetime(2026, 8, 6),
        )


def test_discovery_corpus_cannot_create_evaluation_or_action_receipt() -> None:
    for operation in (RetrievalOperation.EVALUATE, RetrievalOperation.ACTION_DRAFT):
        with pytest.raises(ValueError, match="active corpus"):
            CatalogRetrievalReceipt(
                query_digest=_A,
                operation=operation,
                corpus=RuleCorpus.DISCOVERY,
                catalog_digest=_B,
                semantic_state=SemanticAvailability.AVAILABLE,
                generation_digest=_C,
                results=(),
            )


def test_available_receipt_requires_generation_and_contiguous_ranks() -> None:
    with pytest.raises(ValueError, match="name a generation"):
        CatalogRetrievalReceipt(
            query_digest=_A,
            operation=RetrievalOperation.DISCOVER,
            corpus=RuleCorpus.ACTIVE,
            catalog_digest=_B,
            semantic_state=SemanticAvailability.AVAILABLE,
            results=(),
        )
    with pytest.raises(ValueError, match="contiguous"):
        CatalogRetrievalReceipt(
            query_digest=_A,
            operation=RetrievalOperation.DISCOVER,
            corpus=RuleCorpus.ACTIVE,
            catalog_digest=_B,
            semantic_state=SemanticAvailability.AVAILABLE,
            generation_digest=_C,
            results=(RetrievalRank("rule:one@1", 2, (("semantic", 0.8),)),),
        )


def test_degraded_receipt_is_read_only_and_replay_stable() -> None:
    receipt = CatalogRetrievalReceipt(
        query_digest=query_digest(" public storage policy "),
        operation=RetrievalOperation.EXPLAIN,
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=_B,
        semantic_state=SemanticAvailability.UNAVAILABLE,
        degraded_reason="embedding-unavailable",
        results=(RetrievalRank("rule:one@1", 1, (("lexical", 0.8),)),),
    )

    assert receipt.execution_authority is False
    assert receipt.digest == receipt.digest


def test_valid_active_generation_is_projection_only() -> None:
    generation = CatalogSearchGeneration(
        generation_id="active-1",
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=_A,
        semantic_schema_digest=_B,
        ontology_release_digest=_C,
        embedding_space_id="catalog-search-384",
        embedding_model_version="embedding:1",
        embedding_dimension=384,
        document_digests=(_D,),
        state=GenerationState.ACTIVE,
        validation_receipt_digest=_A,
        activated_at=datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert generation.projection_authority == "projection_only"
    assert generation.digest.startswith("sha256:")


def test_corpus_scale_generation_uses_bounded_replayable_chunks() -> None:
    digests = tuple(f"sha256:{index:064x}" for index in range(1, 8_550))

    manifest = build_document_digest_manifest(digests)
    generation = CatalogSearchGeneration(
        generation_id="active-corpus-1",
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=_A,
        semantic_schema_digest=_B,
        ontology_release_digest=_C,
        embedding_space_id="catalog-search-384",
        embedding_model_version="embedding:1",
        embedding_dimension=384,
        document_digests=(),
        document_digest_manifest=manifest,
    )

    assert manifest.document_count == 8_549
    assert len(manifest.chunks) == 34
    assert sum(chunk.document_count for chunk in manifest.chunks) == 8_549
    assert all(chunk.document_count <= 256 for chunk in manifest.chunks)
    assert manifest.inline_document_digests == ()
    manifest.verify_document_digests(digests)
    assert generation.digest.startswith("sha256:")


def test_document_digest_manifest_preserves_inline_boundary_compatibility() -> None:
    inline_digests = tuple(f"sha256:{index:064x}" for index in range(1, 257))
    chunked_digests = (*inline_digests, f"sha256:{257:064x}")

    inline_manifest = build_document_digest_manifest(inline_digests)
    chunked_manifest = build_document_digest_manifest(chunked_digests)
    generation = CatalogSearchGeneration(
        generation_id="active-inline-1",
        corpus=RuleCorpus.ACTIVE,
        catalog_digest=_A,
        semantic_schema_digest=_B,
        ontology_release_digest=_C,
        embedding_space_id="catalog-search-384",
        embedding_model_version="embedding:1",
        embedding_dimension=384,
        document_digests=inline_digests,
        document_digest_manifest=inline_manifest,
    )

    assert inline_manifest.inline_document_digests == inline_digests
    assert len(inline_manifest.chunks) == 1
    assert chunked_manifest.inline_document_digests == ()
    assert tuple(chunk.document_count for chunk in chunked_manifest.chunks) == (256, 1)
    assert generation.digest.startswith("sha256:")


def test_generation_rejects_inline_digests_that_do_not_match_manifest() -> None:
    manifest = build_document_digest_manifest((_A, _B))

    with pytest.raises(ValueError, match="inline document digests MUST match"):
        CatalogSearchGeneration(
            generation_id="active-inline-1",
            corpus=RuleCorpus.ACTIVE,
            catalog_digest=_A,
            semantic_schema_digest=_B,
            ontology_release_digest=_C,
            embedding_space_id="catalog-search-384",
            embedding_model_version="embedding:1",
            embedding_dimension=384,
            document_digests=(_A, _C),
            document_digest_manifest=manifest,
        )


def test_document_digest_manifest_rejects_reordering_missing_and_duplicate_rows() -> None:
    digests = tuple(f"sha256:{index:064x}" for index in range(1, 514))
    manifest = build_document_digest_manifest(digests)

    with pytest.raises(ValueError, match="chunk order"):
        CatalogDocumentDigestManifest(
            document_count=manifest.document_count,
            document_digest_root=manifest.document_digest_root,
            chunks=tuple(reversed(manifest.chunks)),
        )
    with pytest.raises(ValueError, match="document count"):
        manifest.verify_document_digests(digests[:-1])
    with pytest.raises(ValueError, match="unique"):
        build_document_digest_manifest((*digests[:-1], digests[0]))


def test_document_digest_manifest_rejects_stale_root_and_overlarge_chunk() -> None:
    manifest = build_document_digest_manifest((_A, _B))

    with pytest.raises(ValueError, match="root mismatch"):
        CatalogDocumentDigestManifest(
            document_count=manifest.document_count,
            document_digest_root=_D,
            chunks=manifest.chunks,
            inline_document_digests=manifest.inline_document_digests,
        )
    with pytest.raises(ValueError, match=r"in \[1, 256\]"):
        CatalogDocumentDigestChunk(
            index=0,
            document_count=257,
            document_digest_root=_A,
        )
    with pytest.raises(ValueError, match="chunk document count"):
        CatalogDocumentDigestManifest(
            document_count=manifest.document_count + 1,
            document_digest_root=manifest.document_digest_root,
            chunks=manifest.chunks,
        )
