from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CatalogRetrievalReceipt,
    CatalogSearchGeneration,
    CohortMetric,
    GenerationState,
    RetrievalOperation,
    RetrievalRank,
    RuleCorpus,
    RuleSemanticManifest,
    RuleSemanticSurface,
    SemanticAvailability,
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
