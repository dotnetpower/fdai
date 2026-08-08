from __future__ import annotations

from collections.abc import Sequence

import pytest
from fdai.rule_catalog.schema.rule_semantic_evaluation import (
    EvaluationQueryOrigin,
    RetrievalEvaluationCase,
    RetrievalEvaluationPolicy,
    evaluate_semantic_surface,
)
from fdai.rule_catalog.schema.rule_semantic_manifest import build_surface_candidate
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    RuleCorpus,
    RuleSemanticManifest,
    SurfaceOrigin,
    ValidationDecision,
)
from fdai.shared.contracts.models import Redistribution

_DIGEST = "sha256:" + "a" * 64


class _Retriever:
    async def search(self, query: str, *, k: int) -> Sequence[str]:
        del k
        if "public" in query.casefold():
            return ("rule:public-access@1",)
        return ()


def _surface(training_query: str = "Block public object storage"):
    manifest = RuleSemanticManifest(
        rule_id="public-access",
        rule_version="1",
        corpus=RuleCorpus.ACTIVE,
        policy_ref="policies/public.rego",
        policy_digest=_DIGEST,
        source_content_digest=_DIGEST,
        parser_id="opa-ast",
        parser_version="1",
        redistribution=Redistribution.EMBEDDABLE,
        resource_type="object-storage",
        ontology_release_digest=_DIGEST,
        signal_refs=("resource.configuration.observed",),
        property_refs=("property.object-storage.public_access",),
        action_type_ref="remediate.disable-public-access",
    )
    return build_surface_candidate(
        manifest,
        surface_id="surface.public-access.en",
        locale="en",
        origin=SurfaceOrigin.AUTHORED,
        intent_ids=("prevent-public-access",),
        concept_refs=("object-storage",),
        aliases=("block public access",),
        training_queries=(training_query,),
        hard_negative_queries=("Enable versioning",),
        producer_ref="catalog:reviewed",
        evidence_refs=("rule:public-access@1",),
    )


def _policy() -> RetrievalEvaluationPolicy:
    return RetrievalEvaluationPolicy(
        top_k=5,
        min_recall_at_k=1.0,
        min_mean_reciprocal_rank=1.0,
        min_no_match_precision=1.0,
    )


async def test_held_out_evaluation_passes_positive_and_no_match_cohorts() -> None:
    cases = (
        RetrievalEvaluationCase(
            "positive-en",
            "Which policy prevents public storage?",
            "en-positive",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "negative-en",
            "Which policy tunes database connections?",
            "en-negative",
            (),
            EvaluationQueryOrigin.PROBE_GENERATED,
            generator_ref="probe:independent@1",
        ),
    )

    receipt = await evaluate_semantic_surface(
        _surface(),
        cases,
        retriever=_Retriever(),
        policy=_policy(),
        evaluator_ref="heimdall:rule-retrieval@1",
    )

    assert receipt.decision is ValidationDecision.PASS
    assert receipt.failure_codes == ()
    assert {item.metric for item in receipt.cohort_metrics} == {
        "recall-at-5",
        "mean-reciprocal-rank",
        "no-match-precision",
    }


async def test_training_query_cannot_leak_into_held_out_evaluation() -> None:
    query = "Which policy prevents public storage?"
    cases = (
        RetrievalEvaluationCase(
            "positive-en",
            query,
            "en-positive",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "negative-en",
            "No matching policy",
            "en-negative",
            (),
            EvaluationQueryOrigin.USER,
        ),
    )

    with pytest.raises(ValueError, match="held-out"):
        await evaluate_semantic_surface(
            _surface(training_query=query),
            cases,
            retriever=_Retriever(),
            policy=_policy(),
            evaluator_ref="heimdall:rule-retrieval@1",
        )


def test_generated_evaluation_case_requires_origin_receipt() -> None:
    with pytest.raises(ValueError, match="generator"):
        RetrievalEvaluationCase(
            "generated",
            "A generated query",
            "en",
            (),
            EvaluationQueryOrigin.ASSURANCE_GENERATED,
        )
