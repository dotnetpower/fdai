"""Question adequacy and metamorphic assurance tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation.question_adequacy import (
    DeterministicAdequacyGate,
    MetamorphicAxis,
    MetamorphicDimension,
    MetamorphicObservation,
    QuestionModelReview,
    evaluate_metamorphic_group,
    evaluate_question_adequacy,
    require_metamorphic_coverage,
)
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict

DIGEST = "sha256:" + "a" * 64
CAMPAIGN_ID = "qs:" + "b" * 64


def _gates(**overrides: AssuranceVerdict):
    names = (
        "semantic",
        "evidence_entailment",
        "completeness",
        "calibration",
        "scope",
        "authority",
    )
    return tuple(
        DeterministicAdequacyGate(
            name=name,
            verdict=overrides.get(name, AssuranceVerdict.PASS),
            receipt_digest=DIGEST,
        )
        for name in names
    )


def _review(
    identity: str,
    family: str,
    *,
    verdict: AssuranceVerdict = AssuranceVerdict.PASS,
    score: int = 4,
) -> QuestionModelReview:
    return QuestionModelReview(
        model_identity=identity,
        model_family=family,
        verdict=verdict,
        criterion_scores=tuple((criterion, score) for criterion in AssuranceCriterion),
        review_digest="sha256:" + identity[-1] * 64,
    )


def test_safety_critical_failure_overrides_model_scores() -> None:
    receipt = evaluate_question_adequacy(
        campaign_id=CAMPAIGN_ID,
        case_id="case-1",
        deterministic_gates=_gates(scope=AssuranceVerdict.FAIL),
        first=_review("reviewer-1", "family-a"),
        second=_review("reviewer-2", "family-b"),
        answer_model_identity="answer-model",
    )

    assert receipt.verdict is AssuranceVerdict.FAIL
    assert receipt.safety_critical_failure is True
    assert receipt.reason == "safety_critical_gate_failed"
    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, safety_critical_failure=False)


def test_reviewer_verdict_disagreement_remains_inconclusive_with_tie_breaker() -> None:
    receipt = evaluate_question_adequacy(
        campaign_id=CAMPAIGN_ID,
        case_id="case-1",
        deterministic_gates=_gates(),
        first=_review("reviewer-1", "family-a"),
        second=_review("reviewer-2", "family-b", verdict=AssuranceVerdict.FAIL, score=2),
        tie_breaker=_review("reviewer-3", "family-c"),
        answer_model_identity="answer-model",
    )

    assert receipt.verdict is AssuranceVerdict.INCONCLUSIVE
    assert receipt.reviewer_disagreement is True
    assert receipt.tie_break_used is False


def test_answer_model_cannot_evaluate_itself_and_families_must_differ() -> None:
    self_review = evaluate_question_adequacy(
        campaign_id=CAMPAIGN_ID,
        case_id="case-1",
        deterministic_gates=_gates(),
        first=_review("reviewer-1", "family-a"),
        second=_review("reviewer-2", "family-b"),
        answer_model_identity="reviewer-1",
    )
    assert self_review.verdict is AssuranceVerdict.INCONCLUSIVE
    assert self_review.reason == "answer_model_cannot_self_evaluate"
    with pytest.raises(ValueError, match="families MUST be distinct"):
        evaluate_question_adequacy(
            campaign_id=CAMPAIGN_ID,
            case_id="case-1",
            deterministic_gates=_gates(),
            first=_review("reviewer-1", "family-a"),
            second=_review("reviewer-2", "family-a"),
            answer_model_identity=None,
        )


def test_model_verdict_must_match_scores() -> None:
    with pytest.raises(ValueError, match="conflicts with criterion scores"):
        _review(
            "reviewer-1",
            "family-a",
            verdict=AssuranceVerdict.PASS,
            score=2,
        )


def _observation(case_id: str, **overrides: object) -> MetamorphicObservation:
    values: dict[str, object] = {
        "case_id": case_id,
        "locale": "en",
        "result_cardinality": 1,
        "access_scope_digest": DIGEST,
        "evidence_posture": QuestionEvidencePosture.FRESH,
        "truncated": False,
        "fact_set_digest": DIGEST,
        "disposition": "answered",
        "semantic_frame_digest": DIGEST,
        "authority_posture": "read_only",
    }
    values.update(overrides)
    return MetamorphicObservation(**values)  # type: ignore[arg-type]


def test_bilingual_paraphrase_allows_only_locale_change() -> None:
    passed = evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="bilingual-1",
        dimension=MetamorphicDimension.BILINGUAL_PARAPHRASE,
        observations=(
            _observation("case-en"),
            _observation("case-ko", locale="ko"),
        ),
    )
    failed = evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="bilingual-2",
        dimension=MetamorphicDimension.BILINGUAL_PARAPHRASE,
        observations=(
            _observation("case-en"),
            _observation("case-ko", locale="ko", authority_posture="draft_only"),
        ),
    )

    assert passed.changed_axes == (MetamorphicAxis.LOCALE,)
    assert passed.passed is True
    with pytest.raises(ValueError, match="digest does not match"):
        replace(passed, passed=False)
    assert failed.passed is False
    assert MetamorphicAxis.AUTHORITY in failed.changed_axes


def test_metamorphic_posture_tokens_are_bounded() -> None:
    with pytest.raises(ValueError, match="evidence posture"):
        _observation("case-1", evidence_posture="x" * 129)


def test_result_cardinality_group_requires_zero_one_and_many() -> None:
    incomplete = evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="cardinality-incomplete",
        dimension=MetamorphicDimension.RESULT_CARDINALITY,
        observations=(
            _observation("zero", result_cardinality=0),
            _observation("one", result_cardinality=1),
        ),
    )
    complete = evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="cardinality-complete",
        dimension=MetamorphicDimension.RESULT_CARDINALITY,
        observations=(
            _observation("zero", result_cardinality=0),
            _observation("one", result_cardinality=1),
            _observation("many", result_cardinality=2),
        ),
    )

    assert incomplete.passed is False
    assert complete.passed is True


def test_evidence_posture_group_requires_all_five_states() -> None:
    observations = tuple(
        _observation(
            f"evidence-{posture.value}",
            evidence_posture=posture,
            disposition=("answered" if posture is QuestionEvidencePosture.FRESH else "held"),
        )
        for posture in QuestionEvidencePosture
    )

    assert not evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="evidence-incomplete",
        dimension=MetamorphicDimension.EVIDENCE_POSTURE,
        observations=observations[:-1],
    ).passed
    assert evaluate_metamorphic_group(
        campaign_id=CAMPAIGN_ID,
        group_id="evidence-complete",
        dimension=MetamorphicDimension.EVIDENCE_POSTURE,
        observations=observations,
    ).passed


def test_semantic_frame_and_authority_are_invariant_for_every_dimension() -> None:
    for dimension in MetamorphicDimension:
        receipt = evaluate_metamorphic_group(
            campaign_id=CAMPAIGN_ID,
            group_id=f"invariant-{dimension.value}",
            dimension=dimension,
            observations=(
                _observation("case-1"),
                _observation(
                    "case-2",
                    semantic_frame_digest="sha256:" + "b" * 64,
                    authority_posture="draft_only",
                ),
            ),
        )
        assert receipt.passed is False


def test_metamorphic_coverage_requires_all_six_dimensions() -> None:
    receipts = tuple(
        evaluate_metamorphic_group(
            campaign_id=CAMPAIGN_ID,
            group_id=f"group-{dimension.value}",
            dimension=dimension,
            observations=(
                (
                    _observation(f"{dimension.value}-zero", result_cardinality=0),
                    _observation(f"{dimension.value}-one", result_cardinality=1),
                    _observation(f"{dimension.value}-many", result_cardinality=2),
                )
                if dimension is MetamorphicDimension.RESULT_CARDINALITY
                else (
                    tuple(
                        _observation(
                            f"{dimension.value}-{posture.value}",
                            evidence_posture=posture,
                            disposition=(
                                "answered" if posture is QuestionEvidencePosture.FRESH else "held"
                            ),
                        )
                        for posture in QuestionEvidencePosture
                    )
                    if dimension is MetamorphicDimension.EVIDENCE_POSTURE
                    else (
                        _observation(f"{dimension.value}-1"),
                        _observation(f"{dimension.value}-2"),
                    )
                )
            ),
        )
        for dimension in MetamorphicDimension
    )

    require_metamorphic_coverage(receipts)
    with pytest.raises(ValueError, match="one group per dimension"):
        require_metamorphic_coverage(receipts[:-1])
