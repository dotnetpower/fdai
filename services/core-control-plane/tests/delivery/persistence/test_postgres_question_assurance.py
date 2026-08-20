"""Question assurance PostgreSQL codec tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.conversation.question_governance import (
    ManualQuestionCampaignReview,
    QuestionFailureDecisionKind,
    QuestionFailureReviewDecision,
    QuestionFailureReviewItem,
)
from fdai.core.conversation.question_novelty import (
    QuestionEmbeddingIdentity,
    QuestionNoveltyRecord,
)
from fdai.core.conversation.question_release_assurance import (
    QuestionReleaseAssuranceReceipt,
)
from fdai.core.conversation.question_release_assurance import (
    _digest as _release_digest,
)
from fdai.core.conversation.question_review_artifact import RepositorySafeQuestionReview
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict
from fdai.delivery.persistence.postgres_question_assurance import (
    _manual_review_from_mapping,
    _manual_review_mapping,
    _novelty_from_mapping,
    _novelty_mapping,
    _release_from_mapping,
    _release_mapping,
    _review_decision_from_mapping,
    _review_decision_mapping,
    _review_item_from_mapping,
    _review_item_mapping,
    _review_projection_from_mapping,
    _review_projection_mapping,
)

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 20, tzinfo=UTC)


def test_question_assurance_codecs_round_trip_without_review_text() -> None:
    novelty = QuestionNoveltyRecord(
        campaign_id="qs:" + "b" * 64,
        case_id="case-1",
        generation_attempt=1,
        perspective="resource",
        locale="en",
        ontology_release_digest=DIGEST,
        question_fingerprint=DIGEST,
        embedding=QuestionEmbeddingIdentity(
            space_digest=DIGEST,
            model_version="embedding-v1",
            dimension=384,
            vector_digest=DIGEST,
        ),
        nearest_question_fingerprint=None,
        max_embedding_similarity=0.1,
        exact_duplicate=False,
        semantic_duplicate=False,
        accepted=True,
        recorded_at=NOW,
    )
    projection = RepositorySafeQuestionReview(
        record_id="review-1",
        campaign_id=novelty.campaign_id,
        case_id=novelty.case_id,
        question_digest=DIGEST,
        answer_digest=DIGEST,
        rationale_digests=(DIGEST,),
        criterion_scores=tuple((criterion, 4) for criterion in AssuranceCriterion),
        adequacy_verdict=AssuranceVerdict.PASS,
        adequacy_receipt_digest=DIGEST,
        retention_policy_digest=DIGEST,
        recorded_at=NOW,
        delete_after=NOW + timedelta(days=30),
    )
    item = QuestionFailureReviewItem(
        review_id="failure-1",
        campaign_id=novelty.campaign_id,
        case_id=novelty.case_id,
        semantic_pair_id="pair-1",
        ontology_release_digest=DIGEST,
        question_digest=DIGEST,
        answer_digest=DIGEST,
        adequacy_receipt_digest=DIGEST,
        submitted_at=NOW,
    )
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
    manual = ManualQuestionCampaignReview(
        campaign_id=novelty.campaign_id,
        ontology_release_digest=DIGEST,
        novelty_rate=0.1,
        new_failure_count=0,
        coverage_delta_count=0,
        human_principal_digest=DIGEST,
        human_review_receipt_digest=DIGEST,
        reviewed_at=NOW,
    )
    release_body = {
        "passed": True,
        "reason": "question_release_assurance_passed",
        "ontology_release_digest": DIGEST,
        "generated_campaign_id": novelty.campaign_id,
        "golden_receipt_digest": DIGEST,
        "generated_receipt_digest": DIGEST,
        "adequacy_receipt_digests": (DIGEST,),
        "metamorphic_receipt_digests": (DIGEST,),
        "execution_authority": False,
    }
    release = QuestionReleaseAssuranceReceipt(
        **release_body,
        receipt_digest=_release_digest(release_body),
    )

    novelty_payload = _novelty_mapping(novelty)
    projection_payload = _review_projection_mapping(projection)
    assert _novelty_from_mapping(novelty_payload) == novelty
    assert _review_projection_from_mapping(projection_payload) == projection
    assert _review_item_from_mapping(_review_item_mapping(item)) == item
    assert _review_decision_from_mapping(_review_decision_mapping(decision)) == decision
    assert _manual_review_from_mapping(_manual_review_mapping(manual)) == manual
    assert _release_from_mapping(_release_mapping(release)) == release
    assert "question" not in projection_payload
    assert "answer" not in projection_payload
    assert "rationales" not in projection_payload
