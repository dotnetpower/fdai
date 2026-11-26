"""Private and repository-safe question review artifact tests."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.conversation.question_review_artifact import (
    PrivateQuestionReviewRecord,
    QuestionReviewRetentionPolicy,
    append_private_review_artifact,
    project_repository_safe_review,
)
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _policy() -> QuestionReviewRetentionPolicy:
    return QuestionReviewRetentionPolicy(
        retention_days=30,
        max_records=100,
        policy_digest=DIGEST,
    )


def _record() -> PrivateQuestionReviewRecord:
    return PrivateQuestionReviewRecord(
        record_id="review-1",
        campaign_id="qs:" + "b" * 64,
        case_id="case-1",
        question="What is the selected resource state?",
        answer="The selected resource is available.",
        rationales=("The answer follows the cited state evidence.",),
        criterion_scores=tuple((criterion, 4) for criterion in AssuranceCriterion),
        adequacy_verdict=AssuranceVerdict.PASS,
        adequacy_receipt_digest=DIGEST,
        recorded_at=NOW,
        delete_after=NOW + timedelta(days=30),
    )


def test_private_artifact_is_mode_0600_and_retains_bounded_text(tmp_path: Path) -> None:
    path = tmp_path / "question-review.jsonl"

    append_private_review_artifact(path, retention=_policy(), records=(_record(),))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["question"] == _record().question
    assert stored["answer"] == _record().answer
    assert stored["rationales"] == list(_record().rationales)
    assert stored["retention_days"] == 30


def test_private_artifact_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "link.jsonl"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="MUST NOT be a symlink"):
        append_private_review_artifact(link, retention=_policy(), records=(_record(),))


def test_private_artifact_enforces_total_retention_record_bound(tmp_path: Path) -> None:
    path = tmp_path / "question-review.jsonl"
    policy = QuestionReviewRetentionPolicy(
        retention_days=30,
        max_records=1,
        policy_digest=DIGEST,
    )
    append_private_review_artifact(path, retention=policy, records=(_record(),))

    with pytest.raises(ValueError, match="retention record bound"):
        append_private_review_artifact(path, retention=policy, records=(_record(),))


def test_repository_safe_projection_contains_no_review_text() -> None:
    record = _record()
    projection = project_repository_safe_review(record, retention=_policy())

    rendered = repr(projection)
    assert record.question not in rendered
    assert record.answer not in rendered
    assert record.rationales[0] not in rendered
    assert projection.question_digest.startswith("sha256:")
    assert projection.rationale_digests[0].startswith("sha256:")


def test_projection_rejects_retention_beyond_policy() -> None:
    record = _record()

    with pytest.raises(ValueError, match="exceeds the retention policy"):
        project_repository_safe_review(
            PrivateQuestionReviewRecord(
                record_id=record.record_id,
                campaign_id=record.campaign_id,
                case_id=record.case_id,
                question=record.question,
                answer=record.answer,
                rationales=record.rationales,
                criterion_scores=record.criterion_scores,
                adequacy_verdict=record.adequacy_verdict,
                adequacy_receipt_digest=record.adequacy_receipt_digest,
                recorded_at=record.recorded_at,
                delete_after=record.recorded_at + timedelta(days=31),
            ),
            retention=_policy(),
        )


def test_repository_safe_projection_revalidates_digests() -> None:
    projection = project_repository_safe_review(_record(), retention=_policy())

    with pytest.raises(ValueError, match="question"):
        type(projection)(
            record_id=projection.record_id,
            campaign_id=projection.campaign_id,
            case_id=projection.case_id,
            question_digest="not-a-digest",
            answer_digest=projection.answer_digest,
            rationale_digests=projection.rationale_digests,
            criterion_scores=projection.criterion_scores,
            adequacy_verdict=projection.adequacy_verdict,
            adequacy_receipt_digest=projection.adequacy_receipt_digest,
            retention_policy_digest=projection.retention_policy_digest,
            recorded_at=projection.recorded_at,
            delete_after=projection.delete_after,
        )
