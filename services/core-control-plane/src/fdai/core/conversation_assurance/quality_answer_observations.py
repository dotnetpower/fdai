"""Qualification contributions from deterministic answer plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation.answer_plan import (
    AnswerFormat,
    AnswerPlan,
    AnswerSection,
    DetailLevel,
)
from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)


@dataclass(frozen=True, slots=True)
class AnswerPlanScenarioResult:
    case_id: str
    expected_format: AnswerFormat
    expected_sections: tuple[AnswerSection, ...]
    expected_detail_level: DetailLevel
    expected_max_words: int
    actual: AnswerPlan
    evidence_digest: str


def observe_answer_plan(
    result: AnswerPlanScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure answer structure and depth from one deterministic plan."""

    _require_digest(result.evidence_digest)
    if result.expected_max_words < 1:
        raise ValueError("expected_max_words MUST be positive")
    observed_digest = _digest(result.actual.to_dict())
    return (
        _contribution(
            result,
            item_id=7,
            correct=result.actual.format is result.expected_format
            and result.actual.sections == result.expected_sections,
            reason="answer_format_and_sections_match",
            observed_digest=observed_digest,
        ),
        _contribution(
            result,
            item_id=8,
            correct=result.actual.detail_level is result.expected_detail_level
            and result.actual.max_words == result.expected_max_words,
            reason="answer_detail_and_word_budget_match",
            observed_digest=observed_digest,
        ),
    )


def _contribution(
    result: AnswerPlanScenarioResult,
    *,
    item_id: int,
    correct: bool,
    reason: str,
    observed_digest: str,
) -> QualificationDimensionContribution:
    item = CHATOPS_QUALITY_CONTRACT_V1.items[item_id - 1]
    return QualificationDimensionContribution(
        case_id=result.case_id,
        item_id=item_id,
        workstream=item.workstream,
        metric=item.metric,
        dimension=QualityDimension.FUNCTIONAL_CORRECTNESS,
        value=1.0 if correct else 0.0,
        reason_code=reason,
        evidence_ref_digests=(result.evidence_digest, observed_digest),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _require_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("scenario evidence_digest MUST be a lowercase SHA-256 digest")


__all__ = ["AnswerPlanScenarioResult", "observe_answer_plan"]
