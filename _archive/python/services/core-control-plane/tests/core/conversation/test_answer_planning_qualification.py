"""Shadow Answer Planning Round qualification tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.conversation.answer_planning_qualification import (
    AnswerPlanningEvaluationBatch,
    AnswerPlanningEvaluationSample,
    AnswerPlanningQualificationPolicy,
    PlanningEvaluationLocale,
    evaluate_answer_planning_qualification,
)


def _sample(index: int, **changes: object) -> AnswerPlanningEvaluationSample:
    defaults: dict[str, object] = {
        "case_id": f"case-{index:03d}",
        "locale": PlanningEvaluationLocale.EN if index < 50 else PlanningEvaluationLocale.KO,
        "baseline_unique_evidence_count": 0,
        "candidate_unique_evidence_count": 1,
        "baseline_correction_required": index % 10 == 0,
        "candidate_correction_required": False,
        "baseline_follow_up_required": index % 5 == 0,
        "candidate_follow_up_required": index % 10 == 0,
        "unsupported_claim_escape": False,
        "authority_violation": False,
        "clean_answer_regression": False,
        "planning_elapsed_ms": 900,
        "added_tokens": 400,
    }
    defaults.update(changes)
    return AnswerPlanningEvaluationSample(**defaults)  # type: ignore[arg-type]


def _batch(
    samples: tuple[AnswerPlanningEvaluationSample, ...] | None = None,
) -> AnswerPlanningEvaluationBatch:
    return AnswerPlanningEvaluationBatch(
        scenario_set_version="answer-planning-v1",
        runner_version="runner-v1",
        samples=samples or tuple(_sample(index) for index in range(100)),
    )


def test_complete_bilingual_batch_is_ready_for_separate_review_only() -> None:
    receipt = evaluate_answer_planning_qualification(_batch())

    assert receipt.ready_for_review is True
    assert receipt.gaps == ()
    assert receipt.sample_count == 100
    assert receipt.english_samples == receipt.korean_samples == 50
    assert receipt.unsupported_claim_escapes == 0
    assert receipt.authority_violations == 0
    assert receipt.clean_answer_regressions == 0
    assert receipt.p95_elapsed_ms == 900
    assert receipt.max_added_tokens == 400
    assert receipt.unique_evidence_gain_rate == 1.0
    assert receipt.candidate_correction_rate < receipt.baseline_correction_rate
    assert receipt.candidate_follow_up_rate < receipt.baseline_follow_up_rate
    assert len(receipt.evidence_digest) == 64


@pytest.mark.parametrize(
    ("changes", "gap", "change_all"),
    [
        ({"unsupported_claim_escape": True}, "unsupported_claim_escapes=1", False),
        ({"authority_violation": True}, "authority_violations=1", False),
        ({"clean_answer_regression": True}, "clean_answer_regressions=1", False),
        (
            {"planning_elapsed_ms": 1_201},
            "p95_elapsed_ms=1201>max_p95_elapsed_ms=1200",
            True,
        ),
        (
            {"added_tokens": 801},
            "max_added_tokens=801>max_added_tokens_budget=800",
            False,
        ),
        (
            {"candidate_unique_evidence_count": 0},
            "unique_evidence_gain_rate=0.990<min_unique_evidence_gain_rate=1.000",
            False,
        ),
        (
            {"candidate_correction_required": True},
            "candidate_correction_rate=1.000>baseline_correction_rate=0.100",
            True,
        ),
        (
            {"candidate_follow_up_required": True},
            "candidate_follow_up_rate=1.000>baseline_follow_up_rate=0.200",
            True,
        ),
    ],
)
def test_each_guard_blocks_readiness(
    changes: dict[str, object],
    gap: str,
    change_all: bool,
) -> None:
    samples = list(_batch().samples)
    if change_all:
        samples = [replace(sample, **changes) for sample in samples]  # type: ignore[arg-type]
    else:
        samples[1] = replace(samples[1], **changes)  # type: ignore[arg-type]
    policy = AnswerPlanningQualificationPolicy(min_unique_evidence_gain_rate=1.0)

    receipt = evaluate_answer_planning_qualification(
        _batch(tuple(samples)),
        policy=policy,
    )

    assert receipt.ready_for_review is False
    assert gap in receipt.gaps


def test_incomplete_or_unbalanced_corpus_is_not_ready() -> None:
    receipt = evaluate_answer_planning_qualification(_batch(tuple(_sample(i) for i in range(10))))

    assert receipt.ready_for_review is False
    assert receipt.gaps == (
        "sample_count=10<min_samples=100",
        "english_samples=10<min_samples_per_locale=50",
        "korean_samples=0<min_samples_per_locale=50",
    )


def test_batch_rejects_duplicate_case_identity() -> None:
    duplicate = _sample(0)
    with pytest.raises(ValueError, match="case_id values MUST be unique"):
        _batch((duplicate, duplicate))


@pytest.mark.parametrize(
    "changes",
    [
        {"max_p95_elapsed_ms": 1_201},
        {"max_added_tokens": 801},
        {"min_unique_evidence_gain_rate": float("nan")},
    ],
)
def test_policy_cannot_widen_shipping_budgets_or_accept_non_finite_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        AnswerPlanningQualificationPolicy(**changes)  # type: ignore[arg-type]
