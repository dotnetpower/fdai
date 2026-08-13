from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest
from fdai.rule_catalog.schema.rule_semantic_evaluation import (
    EvaluationQueryOrigin,
    RetrievalEvaluationCase,
    RetrievalEvaluationPolicy,
    evaluate_semantic_surface,
)
from fdai.rule_catalog.schema.rule_semantic_manifest import build_surface_candidate
from fdai.rule_catalog.schema.rule_semantic_promotion_review import (
    PromotionReviewDecision,
    assess_surface_promotion_review,
)
from fdai.rule_catalog.schema.rule_semantic_retrieval import (
    CohortMetric,
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
        normalized_query = query.casefold()
        if "public" in normalized_query or "공개" in normalized_query:
            return ("rule:public-access@1",)
        return ()


class _FailingRetriever:
    async def search(self, query: str, *, k: int) -> Sequence[str]:
        del query, k
        raise RuntimeError("semantic generation is stale")


class _PartiallyFailingRetriever:
    async def search(self, query: str, *, k: int) -> Sequence[str]:
        if "temporarily unavailable" in query.casefold():
            raise RuntimeError("semantic generation is partially unavailable")
        return await _Retriever().search(query, k=k)


def _surface(
    training_query: str = "Block public object storage",
    *,
    locale: str = "en",
):
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
        surface_id=f"surface.public-access.{locale}",
        locale=locale,
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
        required_cohorts=("en-negative", "en-positive"),
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
    assert receipt.validation_authority == "validation_only"

    assessment = assess_surface_promotion_review(
        receipt,
        current_policy=_policy(),
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )
    assert assessment.decision is PromotionReviewDecision.ELIGIBLE_FOR_REVIEW
    assert assessment.reason_codes == ()
    assert assessment.review_authority == "review_only"
    assert assessment.promotion_authority is False
    assert assessment.execution_authority is False


async def test_pass_from_previous_policy_is_held_by_current_review_policy() -> None:
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
            EvaluationQueryOrigin.USER,
        ),
    )
    previous_policy = _policy()
    receipt = await evaluate_semantic_surface(
        _surface(),
        cases,
        retriever=_Retriever(),
        policy=previous_policy,
        evaluator_ref="heimdall:rule-retrieval@1",
    )
    current_policy = RetrievalEvaluationPolicy(
        top_k=10,
        min_recall_at_k=1.0,
        min_mean_reciprocal_rank=1.0,
        min_no_match_precision=1.0,
        required_cohorts=previous_policy.required_cohorts,
    )

    assessment = assess_surface_promotion_review(
        receipt,
        current_policy=current_policy,
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )

    assert receipt.decision is ValidationDecision.PASS
    assert receipt.evaluation_policy_digest == previous_policy.digest
    assert assessment.decision is PromotionReviewDecision.HOLD
    assert assessment.reason_codes == ("evaluation-policy-digest-mismatch",)
    assert assessment.review_authority == "review_only"
    assert assessment.promotion_authority is False
    assert assessment.execution_authority is False


async def test_review_assessment_revalidates_passing_receipt_metrics() -> None:
    policy = _policy()
    receipt = await evaluate_semantic_surface(
        _surface(),
        (
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
                EvaluationQueryOrigin.USER,
            ),
        ),
        retriever=_Retriever(),
        policy=policy,
        evaluator_ref="heimdall:rule-retrieval@1",
    )
    tampered_receipt = replace(
        receipt,
        cohort_metrics=tuple(
            CohortMetric(item.cohort, item.metric, 0.0, item.sample_count)
            if item.metric.startswith("recall-at-")
            else item
            for item in receipt.cohort_metrics
        ),
    )

    assessment = assess_surface_promotion_review(
        tampered_receipt,
        current_policy=policy,
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )

    assert assessment.decision is PromotionReviewDecision.HOLD
    assert assessment.reason_codes == ("metric-below-current-threshold:en-positive:recall-at-5",)


async def test_review_assessment_rejects_missing_renamed_and_unknown_schema_evidence() -> None:
    policy = _policy()
    receipt = await evaluate_semantic_surface(
        _surface(),
        (
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
                EvaluationQueryOrigin.USER,
            ),
        ),
        retriever=_Retriever(),
        policy=policy,
        evaluator_ref="heimdall:rule-retrieval@1",
    )
    missing_metric_receipt = replace(
        receipt,
        cohort_metrics=tuple(
            item for item in receipt.cohort_metrics if item.metric != "recall-at-5"
        ),
    )
    renamed_metric_receipt = replace(
        receipt,
        cohort_metrics=tuple(
            CohortMetric(item.cohort, "recall-at-999", item.value, item.sample_count)
            if item.metric == "recall-at-5"
            else item
            for item in receipt.cohort_metrics
        ),
    )
    unknown_schema_receipt = replace(receipt, schema_version="2.0.0")

    missing_assessment = assess_surface_promotion_review(
        missing_metric_receipt,
        current_policy=policy,
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )
    renamed_assessment = assess_surface_promotion_review(
        renamed_metric_receipt,
        current_policy=policy,
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )
    schema_assessment = assess_surface_promotion_review(
        unknown_schema_receipt,
        current_policy=policy,
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )

    assert missing_assessment.decision is PromotionReviewDecision.HOLD
    assert missing_assessment.reason_codes == ("required-metric-missing:en-positive:recall-at-5",)
    assert renamed_assessment.decision is PromotionReviewDecision.HOLD
    assert renamed_assessment.reason_codes == (
        "required-metric-missing:en-positive:recall-at-5",
        "unrecognized-metric:en-positive:recall-at-999",
    )
    assert schema_assessment.decision is PromotionReviewDecision.HOLD
    assert schema_assessment.reason_codes == ("validation-schema-version-mismatch",)


async def test_review_assessment_holds_identity_mismatch_and_missing_cohort() -> None:
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
            EvaluationQueryOrigin.USER,
        ),
    )
    policy = _policy()
    receipt = await evaluate_semantic_surface(
        _surface(),
        cases,
        retriever=_Retriever(),
        policy=policy,
        evaluator_ref="heimdall:rule-retrieval@1",
    )
    policy_with_unmeasured_cohort = RetrievalEvaluationPolicy(
        top_k=policy.top_k,
        min_recall_at_k=policy.min_recall_at_k,
        min_mean_reciprocal_rank=policy.min_mean_reciprocal_rank,
        min_no_match_precision=policy.min_no_match_precision,
        required_cohorts=(*policy.required_cohorts, "ko-positive"),
    )

    assessment = assess_surface_promotion_review(
        receipt,
        current_policy=policy_with_unmeasured_cohort,
        expected_surface_digest="sha256:" + "b" * 64,
        expected_dataset_digest="sha256:" + "c" * 64,
        expected_evaluator_ref="heimdall:rule-retrieval@2",
    )

    assert assessment.decision is PromotionReviewDecision.HOLD
    assert assessment.reason_codes == (
        "dataset-digest-mismatch",
        "evaluation-policy-digest-mismatch",
        "evaluator-ref-mismatch",
        "required-cohort-missing:ko-positive",
        "surface-digest-mismatch",
    )


async def test_held_out_korean_evaluation_passes_positive_and_no_match_cohorts() -> None:
    surface = _surface("공개 개체 스토리지를 차단하는 규칙", locale="ko")
    cases = (
        RetrievalEvaluationCase(
            "positive-ko",
            "개체 스토리지의 공개 액세스를 차단하는 규칙은 무엇인가요?",
            "ko-positive",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "negative-ko",
            "데이터베이스 연결 수를 조정하는 규칙은 무엇인가요?",
            "ko-negative",
            (),
            EvaluationQueryOrigin.ASSURANCE_GENERATED,
            generator_ref="assurance:korean-retrieval@1",
        ),
    )

    receipt = await evaluate_semantic_surface(
        surface,
        cases,
        retriever=_Retriever(),
        policy=_policy(),
        evaluator_ref="heimdall:rule-retrieval-ko@1",
    )

    assert surface.locale == "ko"
    assert surface.execution_authority is False
    assert receipt.decision is ValidationDecision.PASS
    assert receipt.validation_authority == "validation_only"
    assert {item.cohort for item in receipt.cohort_metrics} == {
        "ko-negative",
        "ko-positive",
    }


async def test_korean_training_query_cannot_leak_into_held_out_evaluation() -> None:
    query = "공개 개체 스토리지를 차단하는 규칙"
    cases = (
        RetrievalEvaluationCase(
            "positive-ko",
            query,
            "ko-positive",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "negative-ko",
            "일치하는 규칙 없음",
            "ko-negative",
            (),
            EvaluationQueryOrigin.USER,
        ),
    )

    with pytest.raises(ValueError, match="held-out"):
        await evaluate_semantic_surface(
            _surface(training_query=query, locale="ko"),
            cases,
            retriever=_Retriever(),
            policy=_policy(),
            evaluator_ref="heimdall:rule-retrieval-ko@1",
        )


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


async def test_retrieval_failure_holds_without_false_no_match_credit() -> None:
    cases = (
        RetrievalEvaluationCase(
            "stale-positive",
            "Which policy prevents public storage?",
            "stale-state",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "stale-no-match",
            "Which policy tunes database connections?",
            "stale-state",
            (),
            EvaluationQueryOrigin.ASSURANCE_GENERATED,
            generator_ref="assurance:stale-state@1",
        ),
    )

    receipt = await evaluate_semantic_surface(
        _surface(),
        cases,
        retriever=_FailingRetriever(),
        policy=_policy(),
        evaluator_ref="heimdall:rule-retrieval@1",
    )
    metrics = {(item.cohort, item.metric): item.value for item in receipt.cohort_metrics}

    assert receipt.decision is ValidationDecision.HOLD
    assert receipt.failure_codes == (
        "stale-state-mrr-below-threshold",
        "stale-state-recall-below-threshold",
        "stale-state-retrieval-error",
    )
    assert metrics == {
        ("stale-state", "mean-reciprocal-rank"): 0.0,
        ("stale-state", "recall-at-5"): 0.0,
        ("stale-state", "retrieval-success-rate"): 0.0,
    }
    assert receipt.validation_authority == "validation_only"


async def test_partial_retrieval_degradation_holds_promotion_review() -> None:
    policy = _policy()
    cases = (
        RetrievalEvaluationCase(
            "available-positive",
            "Which policy prevents public storage?",
            "en-positive",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "unavailable-positive",
            "Which public storage policy is temporarily unavailable?",
            "en-positive",
            ("rule:public-access@1",),
            EvaluationQueryOrigin.USER,
        ),
        RetrievalEvaluationCase(
            "available-negative",
            "Which policy tunes database connections?",
            "en-negative",
            (),
            EvaluationQueryOrigin.ASSURANCE_GENERATED,
            generator_ref="assurance:partial-degradation@1",
        ),
    )

    receipt = await evaluate_semantic_surface(
        _surface(),
        cases,
        retriever=_PartiallyFailingRetriever(),
        policy=policy,
        evaluator_ref="heimdall:rule-retrieval@1",
    )
    metrics = {(item.cohort, item.metric): item.value for item in receipt.cohort_metrics}
    assessment = assess_surface_promotion_review(
        receipt,
        current_policy=policy,
        expected_surface_digest=receipt.surface_digest,
        expected_dataset_digest=receipt.dataset_digest,
        expected_evaluator_ref=receipt.evaluator_ref,
    )

    assert metrics[("en-positive", "retrieval-success-rate")] == 0.5
    assert receipt.decision is ValidationDecision.HOLD
    assert "en-positive-retrieval-error" in receipt.failure_codes
    assert assessment.decision is PromotionReviewDecision.HOLD
    assert (
        "metric-below-current-threshold:en-positive:retrieval-success-rate"
        in assessment.reason_codes
    )
    assert assessment.review_authority == "review_only"
    assert assessment.promotion_authority is False
    assert assessment.execution_authority is False
