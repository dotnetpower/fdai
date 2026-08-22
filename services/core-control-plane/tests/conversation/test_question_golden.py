"""Versioned bilingual golden question contract tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation.question_campaign import QuestionCampaignHardZeroCounters
from fdai.core.conversation.question_golden import (
    GoldenAuthorityPosture,
    GoldenCaseCertification,
    GoldenOntologyExpectation,
    GoldenOntologyPath,
    GoldenOntologyPathStep,
    GoldenQuestionCase,
    GoldenSemanticFrame,
    build_golden_corpus,
    evaluate_golden_certification,
)
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture

DIGEST = "sha256:" + "a" * 64


def _case(*, locale: str, case_id: str) -> GoldenQuestionCase:
    return GoldenQuestionCase(
        case_id=case_id,
        semantic_pair_id="resource-state",
        locale=locale,
        question=(
            "What is the current state of the selected resource?"
            if locale == "en"
            else "선택한 리소스의 현재 상태는 무엇인가요?"
        ),
        expected_frame=GoldenSemanticFrame(
            operation="select",
            subject="resource",
            measure_concepts=("status",),
            output_shape="resource_list",
        ),
        required_capabilities=("object_set",),
        allowed_dispositions=("answered", "held"),
        required_facts=("resource.status",),
        forbidden_claims=("execution.completed",),
        evidence_posture=QuestionEvidencePosture.FRESH,
        authority_posture=GoldenAuthorityPosture.READ_ONLY,
    )


def _corpus():
    return build_golden_corpus(
        corpus_version="1.0.0",
        cases=(
            _case(locale="ko", case_id="resource-state-ko"),
            _case(locale="en", case_id="resource-state-en"),
        ),
    )


def _result(case_id: str, **overrides: bool) -> GoldenCaseCertification:
    values = {
        "semantic_frame_matched": True,
        "capabilities_exact": True,
        "disposition_allowed": True,
        "required_facts_present": True,
        "forbidden_claims_absent": True,
        "evidence_posture_matched": True,
        "authority_posture_matched": True,
        "transport_passed": True,
    }
    values.update(overrides)
    return GoldenCaseCertification(case_id=case_id, assessment_digest=DIGEST, **values)


def test_golden_corpus_is_replay_stable_and_bilingual() -> None:
    first = _corpus()
    second = _corpus()

    assert first == second
    assert tuple(item.locale for item in first.cases) == ("en", "ko")
    assert first.cases[0].expectation_digest == first.cases[1].expectation_digest


def test_golden_case_preserves_typed_dataset_dimensions() -> None:
    case = replace(
        _case(locale="en", case_id="resource-state-en"),
        expected_frame=GoldenSemanticFrame(
            operation="select",
            subject="resource",
            measure_concepts=(),
            output_shape=None,
            temporal_scope="current",
        ),
        required_object_types=("BusinessService", "Resource"),
        required_link_types=("service_depends_on_resource",),
        required_function_types=("query.ontology_relationships",),
        expected_ontology=GoldenOntologyExpectation(
            anchor_type="BusinessService",
            target_types=("Resource",),
            paths=(
                GoldenOntologyPath(
                    path_id="service-resource",
                    steps=(
                        GoldenOntologyPathStep(
                            from_type="BusinessService",
                            link_type="service_depends_on_resource",
                            direction="outgoing",
                            to_type="Resource",
                        ),
                    ),
                ),
            ),
            min_traversal_depth=1,
            max_traversal_depth=1,
        ),
        required_limitations=("missing_evidence_must_remain_unknown",),
        runtime_context="server_scope",
        variation_kind="evidence_first",
    )

    assert case.expected_frame.temporal_scope == "current"
    assert case.expected_ontology is not None
    assert case.expected_ontology.paths[0].steps[0].to_type == "Resource"
    assert case.expectation_digest.startswith("sha256:")


def test_golden_corpus_rejects_missing_locale_and_expectation_drift() -> None:
    english = _case(locale="en", case_id="resource-state-en")
    korean = _case(locale="ko", case_id="resource-state-ko")
    with pytest.raises(ValueError, match="exactly en and ko"):
        build_golden_corpus(
            corpus_version="1.0.0",
            cases=(english,),
        )
    with pytest.raises(ValueError, match="expectations MUST be identical"):
        build_golden_corpus(
            corpus_version="1.0.0",
            cases=(english, replace(korean, required_facts=("resource.health",))),
        )


def test_golden_case_rejects_untyped_posture_values() -> None:
    case = _case(locale="en", case_id="resource-state-en")

    with pytest.raises(ValueError, match="evidence posture"):
        replace(case, evidence_posture="fresh")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="authority posture"):
        replace(case, authority_posture="read_only")  # type: ignore[arg-type]


def test_golden_certification_requires_exact_case_coverage() -> None:
    corpus = _corpus()
    with pytest.raises(ValueError, match="exactly cover"):
        evaluate_golden_certification(
            corpus=corpus,
            ontology_release_digest=DIGEST,
            principal_manifest_digests=(DIGEST,),
            results=(_result("resource-state-en"),),
        )


def test_any_golden_gate_failure_blocks_certification() -> None:
    corpus = _corpus()
    receipt = evaluate_golden_certification(
        corpus=corpus,
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
        results=(
            _result("resource-state-en"),
            _result("resource-state-ko", forbidden_claims_absent=False),
        ),
    )

    assert receipt.passed is False
    assert receipt.passed_case_count == 1
    assert receipt.reason == "golden_case_failed"

    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, receipt_digest="sha256:" + "0" * 64)


def test_any_golden_hard_zero_regression_blocks_certification() -> None:
    corpus = _corpus()
    receipt = evaluate_golden_certification(
        corpus=corpus,
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
        results=(
            _result("resource-state-en"),
            GoldenCaseCertification(
                case_id="resource-state-ko",
                semantic_frame_matched=True,
                capabilities_exact=True,
                disposition_allowed=True,
                required_facts_present=True,
                forbidden_claims_absent=True,
                evidence_posture_matched=True,
                authority_posture_matched=True,
                transport_passed=True,
                assessment_digest=DIGEST,
                hard_zero=QuestionCampaignHardZeroCounters(
                    unauthorized_execution_count=1,
                ),
            ),
        ),
    )

    assert receipt.passed is False
