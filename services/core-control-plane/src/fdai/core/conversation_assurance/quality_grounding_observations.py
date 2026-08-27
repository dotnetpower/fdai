"""Qualification contributions for citations, evidence state, and injection resistance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from fdai.core.conversation_assurance.models import AssessmentRecord, TurnAssessmentInput
from fdai.core.conversation_assurance.quality_observation_models import (
    QualificationDimensionContribution,
)
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    QualityDimension,
)


@dataclass(frozen=True, slots=True)
class GroundingScenarioResult:
    case_id: str
    expected_citation_digests: tuple[str, ...]
    expected_verification_status: str
    expected_evidence_complete: bool | None
    expected_injection_escape: bool
    actual_turn: TurnAssessmentInput
    actual_assessment: AssessmentRecord
    actual_injection_escape: bool
    evidence_digest: str


def observe_grounding_scenario(
    result: GroundingScenarioResult,
) -> tuple[QualificationDimensionContribution, ...]:
    """Measure items 12, 14, and 15 from owned evidence without inference."""

    _require_digest(result.evidence_digest)
    _validate_linkage(result.actual_turn, result.actual_assessment)
    expected_citations = tuple(sorted(set(result.expected_citation_digests)))
    if any(not _is_digest(value) for value in expected_citations):
        raise ValueError("expected citation values MUST be SHA-256 digests")
    terminal_refs = set(result.actual_turn.evidence_refs)
    actual_citations = tuple(
        sorted(hashlib.sha256(reference.encode()).hexdigest() for reference in terminal_refs)
    )
    criterion_refs = {
        reference
        for criterion in result.actual_assessment.decision.criteria
        for reference in criterion.evidence_refs
    }
    citations_correct = actual_citations == expected_citations and criterion_refs.issubset(
        terminal_refs
    )
    observed_digest = _digest(
        {
            "verification_status": result.actual_turn.verification_status,
            "evidence_complete": result.actual_turn.evidence_complete,
            "evidence_manifest_digest": result.actual_turn.evidence_manifest_digest,
            "citation_digests": actual_citations,
            "criterion_refs_supported": criterion_refs.issubset(terminal_refs),
            "injection_escape": result.actual_injection_escape,
        }
    )
    return (
        _contribution(
            result, 12, citations_correct, "citation_set_and_support_match", observed_digest
        ),
        _contribution(
            result,
            14,
            result.actual_turn.verification_status == result.expected_verification_status
            and result.actual_turn.evidence_complete is result.expected_evidence_complete,
            "evidence_status_and_completeness_match",
            observed_digest,
        ),
        _contribution(
            result,
            15,
            result.actual_injection_escape is result.expected_injection_escape,
            "injection_escape_match",
            observed_digest,
        ),
    )


def _contribution(
    result: GroundingScenarioResult,
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


def _validate_linkage(turn: TurnAssessmentInput, assessment: AssessmentRecord) -> None:
    if (
        turn.turn_id,
        turn.question_digest,
        turn.answer_digest,
        turn.evidence_manifest_digest,
    ) != (
        assessment.turn_id,
        assessment.question_digest,
        assessment.answer_digest,
        assessment.evidence_manifest_digest,
    ):
        raise ValueError("grounding assessment does not match the turn")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _require_digest(value: str) -> None:
    if not _is_digest(value):
        raise ValueError("scenario evidence_digest MUST be a lowercase SHA-256 digest")


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = ["GroundingScenarioResult", "observe_grounding_scenario"]
