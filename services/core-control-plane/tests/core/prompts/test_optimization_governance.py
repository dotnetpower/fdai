"""Prompt optimization promotion and rollback evidence tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.prompts.optimization_governance import (
    PromptCohortEvidence,
    PromptPromotionAction,
    PromptPromotionDecision,
    evaluate_prompt_promotion,
)

_D = "sha256:" + ("a" * 64)
_MODEL = "sha256:" + ("b" * 64)
_COHORT = "sha256:" + ("c" * 64)
_SHAPE = "sha256:" + ("d" * 64)


def _evidence(profile: str, *, quality: int = 100, safety: int = 100, tokens: int = 1000):
    return PromptCohortEvidence(
        profile_id=profile,
        profile_digest=_D,
        model_binding_digest=_MODEL,
        cohort_digest=_COHORT,
        sample_count=100,
        quality_passed=quality,
        safety_passed=safety,
        prompt_tokens=tokens,
        completion_tokens=100,
        planning_shapes_digest=_SHAPE,
    )


def test_promotes_exact_safe_non_regressing_token_reduction() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    decision = evaluate_prompt_promotion(
        baseline=_evidence("baseline"),
        treatment=_evidence("treatment", tokens=700),
        decided_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert decision.action is PromptPromotionAction.PROMOTE
    assert decision.reason_codes == ()
    assert decision.execution_authority is False


def test_safety_or_quality_regression_rolls_back() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    decision = evaluate_prompt_promotion(
        baseline=_evidence("baseline"),
        treatment=_evidence("treatment", quality=99, safety=99, tokens=700),
        decided_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert decision.action is PromptPromotionAction.ROLLBACK
    assert decision.reason_codes == ("quality_regression", "safety_regression")


def test_unreviewed_small_cohort_holds() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    treatment = _evidence("treatment", tokens=700)
    treatment = replace(treatment, sample_count=25, quality_passed=25, safety_passed=25)
    decision = evaluate_prompt_promotion(
        baseline=treatment,
        treatment=treatment,
        decided_at=now,
        expires_at=now + timedelta(days=7),
    )

    assert decision.action is PromptPromotionAction.HOLD
    assert decision.reason_codes == ("cohort_too_small", "no_prompt_token_reduction")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_count", True),
        ("quality_passed", 100.0),
        ("safety_passed", "100"),
        ("prompt_tokens", 1000.0),
        ("completion_tokens", False),
    ],
)
def test_evidence_rejects_non_integer_measurements(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=f"{field} MUST be one integer"):
        replace(_evidence("treatment"), **{field: value})


def test_decision_rejects_untyped_action_and_authority() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    baseline = _evidence("baseline")
    treatment = _evidence("treatment", tokens=700)
    decision = evaluate_prompt_promotion(
        baseline=baseline,
        treatment=treatment,
        decided_at=now,
        expires_at=now + timedelta(days=7),
    )

    with pytest.raises(TypeError, match="PromptPromotionAction"):
        replace(decision, action="promote")
    with pytest.raises(TypeError, match="one boolean"):
        replace(decision, execution_authority=0)

    assert isinstance(decision, PromptPromotionDecision)
