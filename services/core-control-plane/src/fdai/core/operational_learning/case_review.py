"""Immutable case-review contracts shared by Norns and Mimir validation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeGuard

_IDENTIFIER = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_REVIEW_FIELDS = frozenset(
    {
        "case_ref",
        "event_time_cutoff",
        "source_kind",
        "source_identity_digest",
        "source_synthetic",
        "evidence_complete",
        "conflict_digests",
    }
)


class CaseReviewError(ValueError):
    """Bounded reason for one rejected immutable case review."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ImmutableCaseRef:
    case_id: str
    revision: int
    manifest_digest: str

    @classmethod
    def parse(cls, value: object) -> ImmutableCaseRef:
        if not isinstance(value, str) or len(value) > 384:
            raise CaseReviewError("immutable_case_refs_invalid")
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "case-history":
            raise CaseReviewError("immutable_case_refs_invalid")
        case_id, revision_text, manifest_digest = parts[1:]
        if (
            not case_id
            or len(case_id) > 256
            or _IDENTIFIER.fullmatch(case_id) is None
            or not revision_text.isascii()
            or not revision_text.isdecimal()
            or int(revision_text) < 1
            or _SHA256.fullmatch(manifest_digest) is None
        ):
            raise CaseReviewError("immutable_case_refs_invalid")
        return cls(
            case_id=case_id,
            revision=int(revision_text),
            manifest_digest=manifest_digest,
        )

    @property
    def value(self) -> str:
        return f"case-history:{self.case_id}:{self.revision}:{self.manifest_digest}"


@dataclass(frozen=True, slots=True)
class OperationalCaseReview:
    """Mimir's bounded review projection for one immutable case reference."""

    case_ref: str
    event_time_cutoff: datetime
    source_kind: str
    source_identity_digest: str
    source_synthetic: bool
    evidence_complete: bool
    conflict_digests: tuple[str, ...]

    @classmethod
    def parse(cls, value: object) -> OperationalCaseReview:
        if not isinstance(value, Mapping) or set(value) != _CASE_REVIEW_FIELDS:
            raise CaseReviewError("case_review_invalid")
        case_ref = ImmutableCaseRef.parse(value.get("case_ref")).value
        cutoff_raw = value.get("event_time_cutoff")
        if not isinstance(cutoff_raw, str):
            raise CaseReviewError("case_review_invalid")
        try:
            cutoff = datetime.fromisoformat(cutoff_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CaseReviewError("case_review_invalid") from exc
        if cutoff.tzinfo is None:
            raise CaseReviewError("case_review_invalid")
        source_kind = value.get("source_kind")
        source_synthetic = value.get("source_synthetic")
        evidence_complete = value.get("evidence_complete")
        if source_kind not in {"live", "frozen_benchmark"}:
            raise CaseReviewError("case_review_invalid")
        if not isinstance(source_synthetic, bool) or not isinstance(evidence_complete, bool):
            raise CaseReviewError("case_review_invalid")
        source_identity = value.get("source_identity_digest")
        if not isinstance(source_identity, str) or _SHA256.fullmatch(source_identity) is None:
            raise CaseReviewError("case_review_invalid")
        conflicts = _digests(value.get("conflict_digests"))
        if not evidence_complete:
            raise CaseReviewError("case_evidence_incomplete")
        if conflicts:
            raise CaseReviewError("case_evidence_conflicting")
        if source_kind == "live" and source_synthetic:
            raise CaseReviewError("case_evidence_synthetic_live")
        return cls(
            case_ref=case_ref,
            event_time_cutoff=cutoff,
            source_kind=source_kind,
            source_identity_digest=source_identity,
            source_synthetic=source_synthetic,
            evidence_complete=evidence_complete,
            conflict_digests=conflicts,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "case_ref": self.case_ref,
            "event_time_cutoff": self.event_time_cutoff.isoformat(),
            "source_kind": self.source_kind,
            "source_identity_digest": self.source_identity_digest,
            "source_synthetic": self.source_synthetic,
            "evidence_complete": self.evidence_complete,
            "conflict_digests": list(self.conflict_digests),
        }


def parse_case_reviews(
    value: object,
    case_refs: tuple[str, ...],
) -> tuple[OperationalCaseReview, ...]:
    if not _is_sequence(value) or len(value) != len(case_refs):
        raise CaseReviewError("case_review_invalid")
    reviews = tuple(OperationalCaseReview.parse(item) for item in value)
    by_ref = {review.case_ref: review for review in reviews}
    if len(by_ref) != len(reviews) or set(by_ref) != set(case_refs):
        raise CaseReviewError("case_review_conflict")
    return tuple(by_ref[case_ref] for case_ref in case_refs)


def validate_case_review_window(
    reviews: tuple[OperationalCaseReview, ...],
    *,
    reviewed_at: datetime,
    maximum_age: timedelta,
) -> None:
    if reviewed_at.tzinfo is None or maximum_age <= timedelta(0):
        raise ValueError("case review window MUST be timezone-aware and positive")
    for review in reviews:
        if review.event_time_cutoff > reviewed_at:
            raise CaseReviewError("case_evidence_future")
        if reviewed_at - review.event_time_cutoff > maximum_age:
            raise CaseReviewError("case_evidence_stale")


def _digests(value: object) -> tuple[str, ...]:
    if not _is_sequence(value) or len(value) > 256:
        raise CaseReviewError("case_review_invalid")
    digests: list[str] = []
    for item in value:
        if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
            raise CaseReviewError("case_review_invalid")
        digests.append(item)
    return tuple(sorted(set(digests)))


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


__all__ = [
    "CaseReviewError",
    "ImmutableCaseRef",
    "OperationalCaseReview",
    "parse_case_reviews",
    "validate_case_review_window",
]
