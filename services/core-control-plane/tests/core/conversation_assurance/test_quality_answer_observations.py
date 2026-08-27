from __future__ import annotations

import pytest
from fdai.core.conversation.answer_plan import (
    AnswerFormat,
    AnswerIntent,
    AnswerPlan,
    AnswerSection,
    AudienceLevel,
    DetailLevel,
    DiscussPolicy,
    EvidenceRequirement,
)
from fdai.core.conversation_assurance.quality_answer_observations import (
    AnswerPlanScenarioResult,
    observe_answer_plan,
)

_EVIDENCE = "a" * 64


def _plan() -> AnswerPlan:
    return AnswerPlan(
        intent=AnswerIntent.DIAGNOSIS,
        detail_level=DetailLevel.DEEP,
        format=AnswerFormat.BULLETS,
        sections=(
            AnswerSection.SYMPTOMS,
            AnswerSection.HYPOTHESES,
            AnswerSection.CHECKS,
        ),
        evidence_requirement=EvidenceRequirement.SERVER_READ_MODEL,
        audience_level=AudienceLevel.TECHNICAL,
        clarification=None,
        max_words=800,
        discuss=DiscussPolicy.SELECTIVE,
        subject="resource-1",
    )


def test_answer_plan_matches_structure_and_depth() -> None:
    plan = _plan()
    contributions = observe_answer_plan(
        AnswerPlanScenarioResult(
            "case-1",
            AnswerFormat.BULLETS,
            plan.sections,
            DetailLevel.DEEP,
            800,
            plan,
            _EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [7, 8]
    assert all(item.value == 1.0 for item in contributions)


def test_answer_plan_mismatches_score_zero_independently() -> None:
    plan = _plan()
    contributions = observe_answer_plan(
        AnswerPlanScenarioResult(
            "case-1",
            AnswerFormat.TABLE,
            plan.sections,
            DetailLevel.DEEP,
            400,
            plan,
            _EVIDENCE,
        )
    )
    assert [item.value for item in contributions] == [0.0, 0.0]


def test_answer_plan_requires_positive_expected_word_budget() -> None:
    with pytest.raises(ValueError, match="positive"):
        observe_answer_plan(
            AnswerPlanScenarioResult(
                "case-1",
                AnswerFormat.BULLETS,
                _plan().sections,
                DetailLevel.DEEP,
                0,
                _plan(),
                _EVIDENCE,
            )
        )
