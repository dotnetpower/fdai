"""Conversation assurance prompt-profile persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    AssuranceDecision,
    AssuranceVerdict,
)
from fdai.core.prompts import PromptProfileEvidence
from fdai.delivery.persistence.postgres_conversation_assurance import (
    _assessment,
    _decision_mapping,
)


def test_decision_mapping_round_trips_prompt_profile_evidence() -> None:
    profile = PromptProfileEvidence(
        profile_id="active.conversation-assurance",
        profile_version=1,
        profile_digest="sha256:" + ("a" * 64),
        system_text_sha256="b" * 64,
        system_token_budget=2048,
        request_token_budget=16_384,
        reserved_output_tokens=1024,
    )
    decision = AssuranceDecision(
        verdict=AssuranceVerdict.PASS,
        content_score=100.0,
        confidence=1.0,
        model_calls=1,
        prompt_profile_evidence=(profile,),
    )
    record = AssessmentRecord(
        assessment_id="assessment-1",
        turn_id="turn-1",
        conversation_id="conversation-1",
        principal_scope="principal-1",
        question_digest="q" * 64,
        answer_digest="a" * 64,
        evidence_manifest_digest="e" * 64,
        rubric_version="1.0.0",
        model_set_digest="m" * 64,
        decision=decision,
        assessed_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    row = {
        "assessment_id": record.assessment_id,
        "turn_id": record.turn_id,
        "conversation_id": record.conversation_id,
        "principal_scope": record.principal_scope,
        "question_digest": record.question_digest,
        "answer_digest": record.answer_digest,
        "evidence_manifest_digest": record.evidence_manifest_digest,
        "rubric_version": record.rubric_version,
        "model_set_digest": record.model_set_digest,
        "state": record.state.value,
        "decision": _decision_mapping(record.decision),
        "assessed_at": record.assessed_at,
    }

    assert _assessment(row) == record
