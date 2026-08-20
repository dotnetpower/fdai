"""Human review promotion and convergence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.question_adequacy import (
    DeterministicAdequacyGate,
    QuestionModelReview,
    evaluate_question_adequacy,
)
from fdai.core.conversation.question_golden import (
    GoldenAuthorityPosture,
    GoldenQuestionCase,
    GoldenSemanticFrame,
    build_golden_corpus,
)
from fdai.core.conversation.question_governance import (
    InMemoryQuestionFailureReviewLedger,
    ManualQuestionCampaignReview,
    QuestionConvergenceProfile,
    QuestionFailureDecisionKind,
    QuestionFailureReviewDecision,
    QuestionFailureReviewItem,
    append_generated_failure_for_review,
    evaluate_question_convergence,
    promote_reviewed_failure,
)
from fdai.core.conversation.question_perspectives import QuestionEvidencePosture
from fdai.core.conversation.question_review_artifact import RepositorySafeQuestionReview
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _golden_case(pair: str, locale: str) -> GoldenQuestionCase:
    return GoldenQuestionCase(
        case_id=f"{pair}-{locale}",
        semantic_pair_id=pair,
        locale=locale,
        question=(
            "What is the selected resource state?"
            if locale == "en"
            else "선택한 리소스 상태를 알려 주세요."
        ),
        expected_frame=GoldenSemanticFrame(
            operation="select",
            subject="resource",
            measure_concepts=("status",),
            output_shape="resource_list",
        ),
        required_capabilities=("object_set",),
        allowed_dispositions=("answered", "held"),
        required_facts=("resource.status",),
        forbidden_claims=("execution.completed",),
        evidence_posture=QuestionEvidencePosture.FRESH,
        authority_posture=GoldenAuthorityPosture.READ_ONLY,
    )


def _corpus():
    return build_golden_corpus(
        corpus_version="1.0.0",
        cases=(_golden_case("existing", "en"), _golden_case("existing", "ko")),
    )


def _item() -> QuestionFailureReviewItem:
    return QuestionFailureReviewItem(
        review_id="review-1",
        campaign_id="qs:" + "b" * 64,
        case_id="generated-1",
        semantic_pair_id="promoted",
        ontology_release_digest=DIGEST,
        question_digest=DIGEST,
        answer_digest=DIGEST,
        adequacy_receipt_digest=DIGEST,
        submitted_at=NOW,
    )


async def test_failure_review_queue_is_append_only_and_requires_existing_item() -> None:
    ledger = InMemoryQuestionFailureReviewLedger()
    item = _item()
    decision = QuestionFailureReviewDecision(
        review_id=item.review_id,
        decision=QuestionFailureDecisionKind.APPROVED,
        human_principal_digest=DIGEST,
        human_authorization_receipt_digest=DIGEST,
        authorization_expires_at=NOW + timedelta(hours=1),
        reason_code="approved_for_golden",
        decided_at=NOW,
        target_corpus_version="1.1.0",
    )

    with pytest.raises(LookupError, match="unavailable"):
        await ledger.append_review_decision(decision)
    assert await ledger.append_review_item(item) is True
    assert await ledger.append_review_item(item) is False
    assert await ledger.append_review_decision(decision) is True
    assert await ledger.append_review_decision(decision) is False


async def test_failed_generated_adequacy_is_automatically_queued() -> None:
    ledger = InMemoryQuestionFailureReviewLedger()
    gates = tuple(
        DeterministicAdequacyGate(
            name=name,
            verdict=(AssuranceVerdict.FAIL if name == "completeness" else AssuranceVerdict.PASS),
            receipt_digest=DIGEST,
        )
        for name in (
            "semantic",
            "evidence_entailment",
            "completeness",
            "calibration",
            "scope",
            "authority",
        )
    )
    reviews = tuple(
        QuestionModelReview(
            model_identity=f"reviewer-{index}",
            model_family=f"family-{index}",
            verdict=AssuranceVerdict.PASS,
            criterion_scores=tuple((criterion, 4) for criterion in AssuranceCriterion),
            review_digest="sha256:" + str(index) * 64,
        )
        for index in (1, 2)
    )
    adequacy = evaluate_question_adequacy(
        campaign_id="qs:" + "b" * 64,
        case_id="generated-1",
        deterministic_gates=gates,
        first=reviews[0],
        second=reviews[1],
        answer_model_identity="answer-model",
    )
    projection = RepositorySafeQuestionReview(
        record_id="review-generated-1",
        campaign_id="qs:" + "b" * 64,
        case_id="generated-1",
        question_digest=DIGEST,
        answer_digest=DIGEST,
        rationale_digests=(DIGEST,),
        criterion_scores=tuple((criterion, 2) for criterion in AssuranceCriterion),
        adequacy_verdict=AssuranceVerdict.FAIL,
        adequacy_receipt_digest=adequacy.receipt_digest,
        retention_policy_digest=DIGEST,
        recorded_at=NOW,
        delete_after=NOW + timedelta(days=30),
    )

    assert await append_generated_failure_for_review(
        ledger=ledger,
        projection=projection,
        adequacy=adequacy,
        ontology_release_digest=DIGEST,
        semantic_pair_id="generated-pair",
    )
    assert await ledger.get_review_item(projection.record_id) is not None
    passing = evaluate_question_adequacy(
        campaign_id="qs:" + "b" * 64,
        case_id="generated-1",
        deterministic_gates=tuple(replace(gate, verdict=AssuranceVerdict.PASS) for gate in gates),
        first=reviews[0],
        second=reviews[1],
        answer_model_identity="answer-model",
    )
    with pytest.raises(ValueError, match="MUST NOT enter"):
        await append_generated_failure_for_review(
            ledger=ledger,
            projection=replace(
                projection,
                adequacy_verdict=AssuranceVerdict.PASS,
                adequacy_receipt_digest=passing.receipt_digest,
            ),
            adequacy=passing,
            ontology_release_digest=DIGEST,
            semantic_pair_id="generated-pair",
        )


def test_failure_decision_requires_current_human_authorization() -> None:
    with pytest.raises(ValueError, match="authorization MUST be current"):
        QuestionFailureReviewDecision(
            review_id="review-1",
            decision=QuestionFailureDecisionKind.REJECTED,
            human_principal_digest=DIGEST,
            human_authorization_receipt_digest=DIGEST,
            authorization_expires_at=NOW,
            reason_code="insufficient_reproduction",
            decided_at=NOW,
        )


def test_golden_promotion_requires_approval_version_bump_and_bilingual_pair() -> None:
    item = _item()
    approved = QuestionFailureReviewDecision(
        review_id=item.review_id,
        decision=QuestionFailureDecisionKind.APPROVED,
        human_principal_digest=DIGEST,
        human_authorization_receipt_digest=DIGEST,
        authorization_expires_at=NOW + timedelta(hours=1),
        reason_code="approved_for_golden",
        decided_at=NOW,
        target_corpus_version="1.1.0",
    )

    promoted, receipt = promote_reviewed_failure(
        corpus=_corpus(),
        item=item,
        decision=approved,
        promoted_cases=(_golden_case("promoted", "en"), _golden_case("promoted", "ko")),
        promoted_at=NOW + timedelta(minutes=1),
    )

    assert promoted.corpus_version == "1.1.0"
    assert len(promoted.cases) == 4
    assert receipt.promoted_corpus_digest == promoted.corpus_digest
    assert receipt.prior_corpus_version == "1.0.0"
    assert receipt.execution_authority is False
    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, promoted_corpus_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="increasing corpus version"):
        promote_reviewed_failure(
            corpus=_corpus(),
            item=item,
            decision=QuestionFailureReviewDecision(
                review_id=item.review_id,
                decision=QuestionFailureDecisionKind.APPROVED,
                human_principal_digest=DIGEST,
                human_authorization_receipt_digest=DIGEST,
                authorization_expires_at=NOW + timedelta(hours=1),
                reason_code="approved_for_golden",
                decided_at=NOW,
                target_corpus_version="1.0.0",
            ),
            promoted_cases=(_golden_case("promoted", "en"), _golden_case("promoted", "ko")),
            promoted_at=NOW + timedelta(minutes=1),
        )


def test_golden_promotion_rechecks_authorization_expiry() -> None:
    item = _item()
    decision = QuestionFailureReviewDecision(
        review_id=item.review_id,
        decision=QuestionFailureDecisionKind.APPROVED,
        human_principal_digest=DIGEST,
        human_authorization_receipt_digest=DIGEST,
        authorization_expires_at=NOW + timedelta(minutes=5),
        reason_code="approved_for_golden",
        decided_at=NOW,
        target_corpus_version="1.1.0",
    )

    with pytest.raises(ValueError, match="authorization is not current"):
        promote_reviewed_failure(
            corpus=_corpus(),
            item=item,
            decision=decision,
            promoted_cases=(
                _golden_case("promoted", "en"),
                _golden_case("promoted", "ko"),
            ),
            promoted_at=NOW + timedelta(minutes=5),
        )


def _campaign(
    index: int,
    *,
    novelty: float = 0.01,
    release: str = DIGEST,
    failures: int = 0,
    coverage_delta: int = 0,
) -> ManualQuestionCampaignReview:
    return ManualQuestionCampaignReview(
        campaign_id="qs:" + f"{index:x}" * 64,
        ontology_release_digest=release,
        novelty_rate=novelty,
        new_failure_count=failures,
        coverage_delta_count=coverage_delta,
        human_principal_digest=DIGEST,
        human_review_receipt_digest="sha256:" + f"{index:x}" * 64,
        reviewed_at=NOW + timedelta(minutes=index),
    )


def _profile() -> QuestionConvergenceProfile:
    return QuestionConvergenceProfile(
        profile_digest=DIGEST,
        human_approver_digest=DIGEST,
        approval_receipt_digest=DIGEST,
        low_novelty_threshold=0.05,
        required_consecutive_runs=2,
    )


def test_convergence_requires_three_manual_reviews_and_low_novelty_streak() -> None:
    insufficient = evaluate_question_convergence(
        target_release_digest=DIGEST,
        profile=_profile(),
        campaigns=(_campaign(1), _campaign(2)),
        evaluated_at=NOW + timedelta(hours=1),
    )
    converged = evaluate_question_convergence(
        target_release_digest=DIGEST,
        profile=_profile(),
        campaigns=(_campaign(1, novelty=0.2), _campaign(2), _campaign(3)),
        evaluated_at=NOW + timedelta(hours=1),
    )

    assert insufficient.stop_scheduling is False
    assert insufficient.reason == "manual_campaign_floor_not_met"
    assert converged.stop_scheduling is True
    assert converged.reason == "approved_convergence_reached"
    assert converged.novelty_curve == (0.2, 0.01, 0.01)
    with pytest.raises(ValueError, match="digest does not match"):
        replace(insufficient, stop_scheduling=True)


def test_failure_coverage_or_release_change_reopens_exploration() -> None:
    base = (_campaign(1), _campaign(2), _campaign(3))
    failure = evaluate_question_convergence(
        target_release_digest=DIGEST,
        profile=_profile(),
        campaigns=base + (_campaign(4, failures=1),),
        evaluated_at=NOW + timedelta(hours=1),
    )
    coverage = evaluate_question_convergence(
        target_release_digest=DIGEST,
        profile=_profile(),
        campaigns=base + (_campaign(4, coverage_delta=1),),
        evaluated_at=NOW + timedelta(hours=1),
    )
    changed_release = "sha256:" + "c" * 64
    release = evaluate_question_convergence(
        target_release_digest=changed_release,
        profile=_profile(),
        campaigns=base,
        evaluated_at=NOW + timedelta(hours=1),
    )

    assert failure.reopened is True
    assert failure.reason == "new_failure_reopened_exploration"
    assert coverage.reopened is True
    assert coverage.reason == "coverage_delta_reopened_exploration"
    assert release.reopened is True
    assert release.reason == "release_change_reopened_exploration"


def test_convergence_rejects_future_review_and_unbounded_threshold() -> None:
    with pytest.raises(ValueError, match="threshold MUST be in"):
        QuestionConvergenceProfile(
            profile_digest=DIGEST,
            human_approver_digest=DIGEST,
            approval_receipt_digest=DIGEST,
            low_novelty_threshold=1.0,
            required_consecutive_runs=2,
        )
    with pytest.raises(ValueError, match="MUST NOT be in the future"):
        evaluate_question_convergence(
            target_release_digest=DIGEST,
            profile=_profile(),
            campaigns=(_campaign(1),),
            evaluated_at=NOW,
        )
