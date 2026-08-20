"""Private review artifacts and repository-safe question assurance projections."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict

_CAMPAIGN_ID_PATTERN = re.compile(r"qs:[0-9a-f]{64}")
_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:-]{0,255}")
_MAX_TEXT_CHARS = 16_384
_MAX_RATIONALES = 32
_MAX_RATIONALE_CHARS = 1_000
_MAX_RECORDS_PER_WRITE = 100


@dataclass(frozen=True, slots=True)
class QuestionReviewRetentionPolicy:
    """Explicit local custody limits for review text."""

    retention_days: int
    max_records: int
    policy_digest: str

    def __post_init__(self) -> None:
        if isinstance(self.retention_days, bool) or not 1 <= self.retention_days <= 365:
            raise ValueError("question review retention_days MUST be in [1, 365]")
        if isinstance(self.max_records, bool) or not 1 <= self.max_records <= 10_000:
            raise ValueError("question review max_records MUST be in [1, 10000]")
        _require_digest("question review retention policy", self.policy_digest)


@dataclass(frozen=True, slots=True)
class PrivateQuestionReviewRecord:
    """Bounded local-only content retained for explicit human review."""

    record_id: str
    campaign_id: str
    case_id: str
    question: str
    answer: str
    rationales: tuple[str, ...]
    criterion_scores: tuple[tuple[AssuranceCriterion, int], ...]
    adequacy_verdict: AssuranceVerdict
    adequacy_receipt_digest: str
    recorded_at: datetime
    delete_after: datetime

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.record_id) is None:
            raise ValueError("question review record id is invalid")
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("question review campaign id is invalid")
        if _IDENTIFIER_PATTERN.fullmatch(self.case_id) is None:
            raise ValueError("question review case id is invalid")
        for name, value in (("question", self.question), ("answer", self.answer)):
            if not value.strip() or len(value) > _MAX_TEXT_CHARS:
                raise ValueError(f"question review {name} MUST be bounded and non-empty")
        if not 1 <= len(self.rationales) <= _MAX_RATIONALES or any(
            not item.strip() or len(item) > _MAX_RATIONALE_CHARS for item in self.rationales
        ):
            raise ValueError("question review rationales MUST be bounded and non-empty")
        if tuple(item[0] for item in self.criterion_scores) != tuple(AssuranceCriterion):
            raise ValueError("question review criteria MUST be complete and ordered")
        if any(
            isinstance(score, bool) or not 0 <= score <= 4 for _, score in self.criterion_scores
        ):
            raise ValueError("question review scores MUST be integers in [0, 4]")
        _require_digest("question review adequacy receipt", self.adequacy_receipt_digest)
        if self.recorded_at.tzinfo is None or self.delete_after.tzinfo is None:
            raise ValueError("question review timestamps MUST be timezone-aware")
        if self.delete_after <= self.recorded_at:
            raise ValueError("question review delete_after MUST follow recorded_at")


@dataclass(frozen=True, slots=True)
class RepositorySafeQuestionReview:
    """Digest-only projection safe for durable shared persistence."""

    record_id: str
    campaign_id: str
    case_id: str
    question_digest: str
    answer_digest: str
    rationale_digests: tuple[str, ...]
    criterion_scores: tuple[tuple[AssuranceCriterion, int], ...]
    adequacy_verdict: AssuranceVerdict
    adequacy_receipt_digest: str
    retention_policy_digest: str
    recorded_at: datetime
    delete_after: datetime

    def __post_init__(self) -> None:
        if _IDENTIFIER_PATTERN.fullmatch(self.record_id) is None:
            raise ValueError("safe question review record id is invalid")
        if _CAMPAIGN_ID_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("safe question review campaign id is invalid")
        if _IDENTIFIER_PATTERN.fullmatch(self.case_id) is None:
            raise ValueError("safe question review case id is invalid")
        for name, value in (
            ("question", self.question_digest),
            ("answer", self.answer_digest),
            ("adequacy", self.adequacy_receipt_digest),
            ("retention policy", self.retention_policy_digest),
        ):
            _require_digest(f"safe question review {name}", value)
        if not 1 <= len(self.rationale_digests) <= _MAX_RATIONALES:
            raise ValueError("safe question review rationale digests MUST be bounded")
        for value in self.rationale_digests:
            _require_digest("safe question review rationale", value)
        if tuple(item[0] for item in self.criterion_scores) != tuple(AssuranceCriterion):
            raise ValueError("safe question review criteria MUST be complete and ordered")
        if any(
            isinstance(score, bool) or not 0 <= score <= 4 for _, score in self.criterion_scores
        ):
            raise ValueError("safe question review scores MUST be integers in [0, 4]")
        if self.recorded_at.tzinfo is None or self.delete_after.tzinfo is None:
            raise ValueError("safe question review timestamps MUST be timezone-aware")
        if self.delete_after <= self.recorded_at:
            raise ValueError("safe question review delete_after MUST follow recorded_at")


def project_repository_safe_review(
    record: PrivateQuestionReviewRecord,
    *,
    retention: QuestionReviewRetentionPolicy,
) -> RepositorySafeQuestionReview:
    """Remove all question, answer, and rationale text from shared evidence."""

    maximum_delete_after = record.recorded_at.timestamp() + retention.retention_days * 86_400
    if record.delete_after.timestamp() > maximum_delete_after:
        raise ValueError("question review delete_after exceeds the retention policy")
    return RepositorySafeQuestionReview(
        record_id=record.record_id,
        campaign_id=record.campaign_id,
        case_id=record.case_id,
        question_digest=_text_digest(record.question),
        answer_digest=_text_digest(record.answer),
        rationale_digests=tuple(_text_digest(item) for item in record.rationales),
        criterion_scores=record.criterion_scores,
        adequacy_verdict=record.adequacy_verdict,
        adequacy_receipt_digest=record.adequacy_receipt_digest,
        retention_policy_digest=retention.policy_digest,
        recorded_at=record.recorded_at,
        delete_after=record.delete_after,
    )


def append_private_review_artifact(
    path: Path,
    *,
    retention: QuestionReviewRetentionPolicy,
    records: Sequence[PrivateQuestionReviewRecord],
) -> None:
    """Append bounded JSONL review text to a regular mode-0600 local file."""

    if not records or len(records) > min(retention.max_records, _MAX_RECORDS_PER_WRITE):
        raise ValueError("question review artifact write exceeds its record bound")
    if path.exists() and path.is_symlink():
        raise ValueError("question review artifact path MUST NOT be a symlink")
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        file_state = os.fstat(descriptor)
        if not stat.S_ISREG(file_state.st_mode):
            raise ValueError("question review artifact MUST be a regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if _count_records(descriptor) + len(records) > retention.max_records:
            raise ValueError("question review artifact exceeds the retention record bound")
        payload = "".join(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "retention_policy_digest": retention.policy_digest,
                    "retention_days": retention.retention_days,
                    "record_id": record.record_id,
                    "campaign_id": record.campaign_id,
                    "case_id": record.case_id,
                    "question": record.question,
                    "answer": record.answer,
                    "rationales": record.rationales,
                    "criterion_scores": [
                        [criterion.value, score] for criterion, score in record.criterion_scores
                    ],
                    "adequacy_verdict": record.adequacy_verdict.value,
                    "adequacy_receipt_digest": record.adequacy_receipt_digest,
                    "recorded_at": record.recorded_at.isoformat(),
                    "delete_after": record.delete_after.isoformat(),
                },
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in records
        ).encode("utf-8")
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("question review artifact write made no progress")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)


def _count_records(descriptor: int) -> int:
    os.lseek(descriptor, 0, os.SEEK_SET)
    count = 0
    while chunk := os.read(descriptor, 65_536):
        count += chunk.count(b"\n")
    os.lseek(descriptor, 0, os.SEEK_END)
    return count


def _text_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _require_digest(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a canonical SHA-256 value")


__all__ = [
    "PrivateQuestionReviewRecord",
    "QuestionReviewRetentionPolicy",
    "RepositorySafeQuestionReview",
    "append_private_review_artifact",
    "project_repository_safe_review",
]
