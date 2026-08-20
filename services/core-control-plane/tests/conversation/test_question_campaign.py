"""Question campaign identity, ledger, and evidence-chain tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.epistemic_coverage import EpistemicStatus
from fdai.core.conversation.question_campaign import (
    CampaignTurnEvidence,
    InMemoryQuestionCampaignLedger,
    QuestionCampaignHardZeroCounters,
    QuestionCampaignState,
    QuestionCampaignTrigger,
    QuestionCaseAttemptRecord,
    build_question_campaign_completion,
    build_question_campaign_identity,
    campaign_epistemic_record,
    campaign_turn_assessment_input,
    evaluate_question_campaign,
)

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _identity(
    *,
    budget: int = 2,
    trigger: QuestionCampaignTrigger = QuestionCampaignTrigger.MANUAL,
):
    return build_question_campaign_identity(
        source_revision="a" * 40,
        ontology_release_digest=DIGEST,
        principal_manifest_digests=(DIGEST,),
        question_universe_digest=DIGEST,
        generation_profile_digest=DIGEST,
        model_set_digest=DIGEST,
        scope_digest=DIGEST,
        started_at=NOW,
        question_budget=budget,
        time_budget_seconds=1_800,
        no_progress_seconds=300,
        token_budget=0 if trigger is QuestionCampaignTrigger.MANUAL else 1_000,
        cost_budget_microusd=0 if trigger is QuestionCampaignTrigger.MANUAL else 10_000,
        trigger=trigger,
    )


def _attempt(identity, case_id: str, **overrides: object) -> QuestionCaseAttemptRecord:
    values: dict[str, object] = {
        "campaign_id": identity.campaign_id,
        "case_id": case_id,
        "validated_question_digest": DIGEST,
        "semantic_turn_id": f"turn:{case_id}",
        "attempt_number": 1,
        "terminal_disposition": "answered",
        "terminal_reason": "verified_answer",
        "failure_kind": None,
        "assessment_id": f"assessment:{case_id}",
        "epistemic_record_digest": DIGEST,
        "latency_ms": 25,
        "model_calls": 1,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_microusd": 7,
    }
    values.update(overrides)
    return QuestionCaseAttemptRecord(**values)  # type: ignore[arg-type]


def test_campaign_identity_is_replay_stable_and_scheduled_budget_is_positive() -> None:
    assert _identity() == _identity()
    assert _identity(trigger=QuestionCampaignTrigger.SCHEDULED).cost_budget_microusd == 10_000
    with pytest.raises(ValueError, match="positive token and cost"):
        replace(
            _identity(trigger=QuestionCampaignTrigger.SCHEDULED),
            cost_budget_microusd=0,
        )


async def test_append_only_ledger_suppresses_replay_and_rejects_conflict() -> None:
    identity = _identity()
    attempt = _attempt(identity, "q:1")
    ledger = InMemoryQuestionCampaignLedger()

    assert await ledger.create_campaign(identity) is True
    assert await ledger.create_campaign(identity) is False
    assert await ledger.append_attempt(attempt) is True
    assert await ledger.append_attempt(attempt) is False
    with pytest.raises(ValueError, match="different content"):
        await ledger.append_attempt(replace(attempt, latency_ms=26))


async def test_campaign_completion_is_append_only_and_binds_selection() -> None:
    identity = _identity(budget=1)
    attempt = _attempt(identity, "q:1")
    ledger = InMemoryQuestionCampaignLedger()
    await ledger.create_campaign(identity)
    await ledger.append_attempt(attempt)
    evaluation = evaluate_question_campaign(
        identity=identity,
        selected_case_ids=("q:1",),
        full_universe_case_ids=("q:1",),
        attempts=(attempt,),
    )
    completion = build_question_campaign_completion(
        identity=identity,
        completed_at=NOW,
        state=QuestionCampaignState.COMPLETED,
        reason="campaign_completed",
        evaluation=evaluation,
        selected_case_ids=("q:1",),
        attempts=(attempt,),
    )

    assert await ledger.finalize_campaign(completion) is True
    assert await ledger.finalize_campaign(completion) is False
    assert await ledger.get_completion(identity.campaign_id) == completion
    assert completion.model_calls == 1
    assert completion.prompt_tokens == 10
    assert completion.completion_tokens == 5
    assert completion.cost_microusd == 7
    with pytest.raises(ValueError, match="conflicts with terminal content"):
        await ledger.finalize_campaign(replace(completion, reason="different_reason"))


async def test_case_claim_rejects_concurrent_owner_and_recovers_after_expiry() -> None:
    identity = _identity(budget=1)
    ledger = InMemoryQuestionCampaignLedger()
    await ledger.create_campaign(identity)

    assert await ledger.claim_case(
        campaign_id=identity.campaign_id,
        case_id="q:1",
        owner_id="runner:first",
        claimed_at=NOW,
        lease_seconds=60,
    )
    assert not await ledger.claim_case(
        campaign_id=identity.campaign_id,
        case_id="q:1",
        owner_id="runner:second",
        claimed_at=NOW + timedelta(seconds=30),
        lease_seconds=60,
    )
    assert await ledger.claim_case(
        campaign_id=identity.campaign_id,
        case_id="q:1",
        owner_id="runner:second",
        claimed_at=NOW + timedelta(seconds=60),
        lease_seconds=60,
    )
    assert not await ledger.release_case_claim(
        campaign_id=identity.campaign_id,
        case_id="q:1",
        owner_id="runner:first",
    )
    assert await ledger.release_case_claim(
        campaign_id=identity.campaign_id,
        case_id="q:1",
        owner_id="runner:second",
    )


def test_partial_subset_is_progress_not_full_universe_closure() -> None:
    identity = _identity(budget=2)
    attempts = (_attempt(identity, "q:1"), _attempt(identity, "q:2"))

    receipt = evaluate_question_campaign(
        identity=identity,
        selected_case_ids=("q:1", "q:2"),
        full_universe_case_ids=("q:1", "q:2", "q:3"),
        attempts=attempts,
    )

    assert receipt.subset_complete is True
    assert receipt.full_universe_closed is False
    assert receipt.release_evidence_eligible is True


def test_any_hard_zero_violation_blocks_release_evidence() -> None:
    identity = _identity(budget=1)
    attempt = _attempt(
        identity,
        "q:1",
        hard_zero=QuestionCampaignHardZeroCounters(
            unverified_impact_promotion_count=1,
        ),
    )

    receipt = evaluate_question_campaign(
        identity=identity,
        selected_case_ids=("q:1",),
        full_universe_case_ids=("q:1",),
        attempts=(attempt,),
    )

    assert receipt.hard_zero.total == 1
    assert receipt.release_evidence_eligible is False
    assert receipt.full_universe_closed is True


def test_release_eligibility_requires_self_verified_epistemic_proof() -> None:
    identity = _identity(budget=1)
    receipt = evaluate_question_campaign(
        identity=identity,
        selected_case_ids=("q:1",),
        full_universe_case_ids=("q:1",),
        attempts=(_attempt(identity, "q:1"),),
    )

    with pytest.raises(ValueError, match="eligibility conflicts"):
        replace(receipt, proof_complete=False)


def test_assurance_and_epistemic_adapters_preserve_exact_identity() -> None:
    assessment = campaign_turn_assessment_input(
        CampaignTurnEvidence(
            turn_id="turn-1",
            conversation_id="conversation-1",
            principal_scope_digest=DIGEST,
            question="What is the selected resource state?",
            answer="The selected resource is available.",
            question_digest=DIGEST,
            answer_digest=DIGEST,
            evidence_manifest_digest=DIGEST,
            evidence_refs=("evidence:1",),
            verification_status="verified",
            verification_authority="ontology_query",
            verification_reason_code="verified_query",
            verification_route_id="semantic.query",
            checks_completed=2,
            checks_total=2,
            evidence_complete=True,
            ontology_release_digest=DIGEST,
            graph_revision=DIGEST,
            locale="en",
            answer_model_identity="model-1",
        )
    )
    epistemic = campaign_epistemic_record(
        case_id="q:1",
        question_universe_digest=DIGEST,
        status=EpistemicStatus.VERIFIED_ANSWER,
        understanding_receipt_digest=DIGEST,
        completeness_receipt_digest=DIGEST,
        claim_proof_receipt_digests=(DIGEST,),
    )

    assert assessment.ontology_release == DIGEST
    assert assessment.principal_scope == DIGEST
    assert epistemic.question_id == "q:1"
    assert epistemic.transport_disposition == "answered"
