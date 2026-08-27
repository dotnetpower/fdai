from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from fdai.core.conversation_assurance.models import (
    AssessmentRecord,
    AssuranceCriterion,
    AssuranceDecision,
    AssuranceVerdict,
    CriterionScore,
    TurnAssessmentInput,
)
from fdai.core.conversation_assurance.quality_grounding_observations import (
    GroundingScenarioResult,
    observe_grounding_scenario,
)

_EVIDENCE = "a" * 64


def _turn(**overrides: object) -> TurnAssessmentInput:
    values: dict[str, object] = {
        "turn_id": "turn-1",
        "conversation_id": "conversation-1",
        "principal_scope": "scope-1",
        "question": "What changed?",
        "answer": "One resource changed.",
        "question_digest": "1" * 64,
        "answer_digest": "2" * 64,
        "evidence_manifest_digest": "3" * 64,
        "evidence_refs": ("evidence-1",),
        "verification_status": "verified",
        "verification_authority": "server",
        "checks_completed": 1,
        "checks_total": 1,
        "evidence_complete": True,
    }
    values.update(overrides)
    return TurnAssessmentInput(**values)  # type: ignore[arg-type]


def _assessment(
    turn: TurnAssessmentInput, *, criterion_ref: str = "evidence-1"
) -> AssessmentRecord:
    score = CriterionScore(
        AssuranceCriterion.FACTUAL_CORRECTNESS,
        4,
        "Supported.",
        (criterion_ref,),
    )
    return AssessmentRecord(
        assessment_id="assessment-1",
        turn_id=turn.turn_id,
        conversation_id=turn.conversation_id,
        principal_scope=turn.principal_scope,
        question_digest=turn.question_digest,
        answer_digest=turn.answer_digest,
        evidence_manifest_digest=turn.evidence_manifest_digest,
        rubric_version="1",
        model_set_digest="models",
        decision=AssuranceDecision(
            AssuranceVerdict.PASS,
            100.0,
            1.0,
            criteria=(score,),
        ),
        assessed_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


def test_grounding_matches_citations_state_and_zero_escape() -> None:
    turn = _turn()
    contributions = observe_grounding_scenario(
        GroundingScenarioResult(
            "case-1",
            (hashlib.sha256(b"evidence-1").hexdigest(),),
            "verified",
            True,
            False,
            turn,
            _assessment(turn),
            False,
            _EVIDENCE,
        )
    )
    assert [item.item_id for item in contributions] == [12, 14, 15]
    assert all(item.value == 1.0 for item in contributions)


def test_unsupported_citation_and_injection_escape_score_zero() -> None:
    turn = _turn()
    contributions = observe_grounding_scenario(
        GroundingScenarioResult(
            "case-1",
            (hashlib.sha256(b"evidence-1").hexdigest(),),
            "verified",
            True,
            False,
            turn,
            _assessment(turn, criterion_ref="fabricated"),
            True,
            _EVIDENCE,
        )
    )
    assert [item.value for item in contributions] == [0.0, 1.0, 0.0]


def test_unavailable_evidence_can_match_an_explicit_expected_state() -> None:
    turn = _turn(
        evidence_refs=(),
        verification_status="unverified",
        evidence_complete=False,
        checks_completed=0,
    )
    contributions = observe_grounding_scenario(
        GroundingScenarioResult(
            "case-1",
            (),
            "unverified",
            False,
            False,
            turn,
            _assessment(turn, criterion_ref=""),
            False,
            _EVIDENCE,
        )
    )
    assert contributions[1].value == 1.0


def test_mismatched_assessment_fails_closed() -> None:
    turn = _turn()
    assessment = _assessment(turn)
    object.__setattr__(assessment, "answer_digest", "4" * 64)
    with pytest.raises(ValueError, match="does not match"):
        observe_grounding_scenario(
            GroundingScenarioResult(
                "case-1",
                (),
                "verified",
                True,
                False,
                turn,
                assessment,
                False,
                _EVIDENCE,
            )
        )
