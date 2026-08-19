"""Question campaign PostgreSQL codec tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation.question_campaign import (
    QuestionCampaignHardZeroCounters,
    QuestionCampaignState,
    QuestionCampaignTrigger,
    QuestionCaseAttemptRecord,
    build_question_campaign_completion,
    build_question_campaign_identity,
    evaluate_question_campaign,
)
from fdai.delivery.persistence.postgres_question_campaign import (
    _attempt_from_mapping,
    _attempt_mapping,
    _completion_from_mapping,
    _completion_mapping,
    _identity_from_mapping,
    _identity_mapping,
)

DIGEST = "sha256:" + "a" * 64


def test_postgres_campaign_codecs_round_trip_without_answer_payloads() -> None:
    identity = build_question_campaign_identity(
        source_revision="a" * 40,
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
        question_universe_digest=DIGEST,
        generation_profile_digest=DIGEST,
        model_set_digest=DIGEST,
        scope_digest=DIGEST,
        started_at=datetime(2026, 8, 19, tzinfo=UTC),
        question_budget=20,
        time_budget_seconds=1_800,
        no_progress_seconds=300,
        token_budget=0,
        cost_budget_microusd=0,
        trigger=QuestionCampaignTrigger.MANUAL,
    )
    attempt = QuestionCaseAttemptRecord(
        campaign_id=identity.campaign_id,
        case_id="q:1",
        validated_question_digest=DIGEST,
        semantic_turn_id="turn:1",
        attempt_number=1,
        terminal_disposition="answered",
        terminal_reason="verified_answer",
        failure_kind=None,
        assessment_id="assessment:1",
        epistemic_record_digest=DIGEST,
        latency_ms=25,
        model_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        cost_microusd=7,
        hard_zero=QuestionCampaignHardZeroCounters(),
    )

    identity_payload = _identity_mapping(identity)
    attempt_payload = _attempt_mapping(attempt)
    evaluation = evaluate_question_campaign(
        identity=identity,
        selected_case_ids=("q:1",),
        full_universe_case_ids=("q:1",),
        attempts=(attempt,),
    )
    completion = build_question_campaign_completion(
        identity=identity,
        completed_at=datetime(2026, 8, 19, 0, 5, tzinfo=UTC),
        state=QuestionCampaignState.COMPLETED,
        reason="campaign_completed",
        evaluation=evaluation,
        selected_case_ids=("q:1",),
        attempts=(attempt,),
    )
    completion_payload = _completion_mapping(completion)

    assert _identity_from_mapping(identity_payload) == identity
    assert _attempt_from_mapping(attempt_payload) == attempt
    assert _completion_from_mapping(completion_payload) == completion
    assert "question" not in attempt_payload
    assert "answer" not in attempt_payload
    assert "provider_payload" not in attempt_payload
    assert "question" not in completion_payload
    assert "answer" not in completion_payload
