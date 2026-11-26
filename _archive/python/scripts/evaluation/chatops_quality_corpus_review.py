#!/usr/bin/env python3
"""Reduce independent hidden-corpus reviews into a content-free receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    sys.path.insert(0, str(_REPO_ROOT / "services/core-control-plane/src"))

from scripts.evaluation.chatops_quality_corpus import HiddenCorpusManifest
from scripts.evaluation.chatops_quality_corpus_manifest import load_manifest

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_REVIEW_BYTES = 16 * 1024 * 1024
_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "corpus_id",
        "corpus_version",
        "manifest_digest",
        "rater_id",
        "rater_family",
        "reviewed_at",
        "entries",
    }
)
_ENTRY_KEYS = frozenset({"case_id", "label_commitment", "decision", "reason_code"})


class ReviewDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class CorpusReviewEntry:
    case_id: str
    label_commitment: str
    decision: ReviewDecision
    reason_code: str

    def __post_init__(self) -> None:
        _token(self.case_id, "review case_id")
        _digest_value(self.label_commitment, "review label_commitment")
        _token(self.reason_code, "review reason_code")


@dataclass(frozen=True, slots=True)
class CorpusRaterReview:
    corpus_id: str
    corpus_version: str
    manifest_digest: str
    rater_id: str
    rater_family: str
    reviewed_at: str
    entries: tuple[CorpusReviewEntry, ...]

    def __post_init__(self) -> None:
        _token(self.corpus_id, "review corpus_id")
        _token(self.corpus_version, "review corpus_version")
        _digest_value(self.manifest_digest, "review manifest_digest")
        _token(self.rater_id, "review rater_id")
        _token(self.rater_family, "review rater_family")
        _timestamp(self.reviewed_at, "review reviewed_at")
        case_ids = tuple(entry.case_id for entry in self.entries)
        if case_ids != tuple(sorted(set(case_ids))):
            raise ValueError("review entries MUST be unique and ordered by case_id")


@dataclass(frozen=True, slots=True)
class CorpusReviewReceipt:
    corpus_id: str
    corpus_version: str
    manifest_digest: str
    case_count: int
    agreement_count: int
    disagreement_count: int
    agreement_rate: float
    minimum_agreement_rate: float
    tie_break_count: int
    accepted_count: int
    rejected_count: int
    rater_review_digests: tuple[str, ...]
    review_complete: bool
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_kind": "hidden_chatops_corpus_review",
            "qualification_authority": False,
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "manifest_digest": self.manifest_digest,
            "case_count": self.case_count,
            "agreement_count": self.agreement_count,
            "disagreement_count": self.disagreement_count,
            "agreement_rate": self.agreement_rate,
            "minimum_agreement_rate": self.minimum_agreement_rate,
            "tie_break_count": self.tie_break_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "rater_review_digests": list(self.rater_review_digests),
            "review_complete": self.review_complete,
            "gaps": list(self.gaps),
        }
        payload["content_digest"] = _digest(payload)
        return payload


def load_review(path: Path) -> CorpusRaterReview:
    return parse_review(_load_owner_only_json(path))


def parse_review(raw: object) -> CorpusRaterReview:
    root = _mapping(raw, "review")
    _exact_keys(root, _ROOT_KEYS, "review")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise ValueError("review schema_version MUST be 1")
    entries = _array(root["entries"], "entries")
    return CorpusRaterReview(
        corpus_id=_string(root["corpus_id"], "corpus_id"),
        corpus_version=_string(root["corpus_version"], "corpus_version"),
        manifest_digest=_string(root["manifest_digest"], "manifest_digest"),
        rater_id=_string(root["rater_id"], "rater_id"),
        rater_family=_string(root["rater_family"], "rater_family"),
        reviewed_at=_string(root["reviewed_at"], "reviewed_at"),
        entries=tuple(_entry(value, index) for index, value in enumerate(entries)),
    )


def reduce_corpus_reviews(
    manifest: HiddenCorpusManifest,
    first: CorpusRaterReview,
    second: CorpusRaterReview,
    *,
    tie_break: CorpusRaterReview | None = None,
) -> CorpusReviewReceipt:
    """Validate independent reviews without exposing per-case decisions."""

    if manifest.review_protocol.minimum_independent_raters != 2:
        raise ValueError("review reducer supports exactly two primary raters")
    _bind_review(manifest, first)
    _bind_review(manifest, second)
    if first.rater_id == second.rater_id or first.rater_family == second.rater_family:
        raise ValueError("primary raters MUST have distinct identities and families")
    expected = {case.case_id: case.label_commitment for case in manifest.cases}
    first_entries = _complete_entries(first, expected)
    second_entries = _complete_entries(second, expected)
    disagreements = tuple(
        case_id
        for case_id in sorted(expected)
        if first_entries[case_id].decision is not second_entries[case_id].decision
    )
    agreement_count = len(expected) - len(disagreements)
    agreement_rate = agreement_count / len(expected)
    gaps: list[str] = []
    if agreement_rate < manifest.review_protocol.minimum_rater_agreement:
        gaps.append(
            f"agreement_rate={agreement_rate:.4f}"
            f"<minimum={manifest.review_protocol.minimum_rater_agreement:.4f}"
        )

    tie_entries: dict[str, CorpusReviewEntry] = {}
    if disagreements:
        if tie_break is None:
            gaps.append(f"tie_break_required={len(disagreements)}")
        else:
            _bind_review(manifest, tie_break)
            if tie_break.rater_id in {first.rater_id, second.rater_id} or (
                tie_break.rater_family in {first.rater_family, second.rater_family}
            ):
                raise ValueError("tie-break rater MUST use a third identity and family")
            tie_entries = {entry.case_id: entry for entry in tie_break.entries}
            if set(tie_entries) != set(disagreements):
                gaps.append("tie_break_coverage_mismatch")
            else:
                _validate_commitments(tie_entries, expected)

    decisions = []
    for case_id in sorted(expected):
        first_decision = first_entries[case_id].decision
        second_decision = second_entries[case_id].decision
        decisions.append(
            first_decision
            if first_decision is second_decision
            else tie_entries.get(case_id, first_entries[case_id]).decision
        )
    reviews = (first, second) if tie_break is None else (first, second, tie_break)
    return CorpusReviewReceipt(
        corpus_id=manifest.corpus_id,
        corpus_version=manifest.corpus_version,
        manifest_digest=manifest.content_digest,
        case_count=len(expected),
        agreement_count=agreement_count,
        disagreement_count=len(disagreements),
        agreement_rate=round(agreement_rate, 4),
        minimum_agreement_rate=manifest.review_protocol.minimum_rater_agreement,
        tie_break_count=len(tie_entries),
        accepted_count=sum(decision is ReviewDecision.ACCEPT for decision in decisions),
        rejected_count=sum(decision is ReviewDecision.REJECT for decision in decisions),
        rater_review_digests=tuple(_review_digest(review) for review in reviews),
        review_complete=not gaps,
        gaps=tuple(gaps),
    )


def _bind_review(manifest: HiddenCorpusManifest, review: CorpusRaterReview) -> None:
    if (
        review.corpus_id != manifest.corpus_id
        or review.corpus_version != manifest.corpus_version
        or review.manifest_digest != manifest.content_digest
    ):
        raise ValueError("review does not match the frozen corpus manifest")


def _complete_entries(
    review: CorpusRaterReview,
    expected: dict[str, str],
) -> dict[str, CorpusReviewEntry]:
    entries = {entry.case_id: entry for entry in review.entries}
    if set(entries) != set(expected):
        raise ValueError("primary review MUST cover every manifest case exactly once")
    _validate_commitments(entries, expected)
    return entries


def _validate_commitments(
    entries: dict[str, CorpusReviewEntry],
    expected: dict[str, str],
) -> None:
    if any(entry.label_commitment != expected[case_id] for case_id, entry in entries.items()):
        raise ValueError("review label commitment does not match the frozen manifest")


def _review_digest(review: CorpusRaterReview) -> str:
    return _digest(
        {
            "corpus_id": review.corpus_id,
            "corpus_version": review.corpus_version,
            "manifest_digest": review.manifest_digest,
            "rater_id": review.rater_id,
            "rater_family": review.rater_family,
            "reviewed_at": review.reviewed_at,
            "entries": [
                {
                    "case_id": entry.case_id,
                    "label_commitment": entry.label_commitment,
                    "decision": entry.decision.value,
                    "reason_code": entry.reason_code,
                }
                for entry in review.entries
            ],
        }
    )


def _entry(raw: object, index: int) -> CorpusReviewEntry:
    field = f"entries[{index}]"
    value = _mapping(raw, field)
    _exact_keys(value, _ENTRY_KEYS, field)
    try:
        decision = ReviewDecision(_string(value["decision"], f"{field}.decision"))
    except ValueError as exc:
        raise ValueError(f"{field}.decision contains an unsupported value") from exc
    return CorpusReviewEntry(
        case_id=_string(value["case_id"], f"{field}.case_id"),
        label_commitment=_string(
            value["label_commitment"],
            f"{field}.label_commitment",
        ),
        decision=decision,
        reason_code=_string(value["reason_code"], f"{field}.reason_code"),
    )


def _load_owner_only_json(path: Path) -> object:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ValueError("review artifact is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValueError("review artifact MUST be an owner-only regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(_MAX_REVIEW_BYTES + 1)
        if len(content) > _MAX_REVIEW_BYTES:
            raise ValueError("review artifact exceeds the maximum size")
        return json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("review artifact is unreadable") from exc
    finally:
        os.close(descriptor)


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{field} MUST be an object with string keys")
    return raw


def _array(raw: object, field: str) -> list[object]:
    if not isinstance(raw, list):
        raise ValueError(f"{field} MUST be an array")
    return raw


def _exact_keys(raw: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    if frozenset(raw) != expected:
        raise ValueError(f"{field} fields differ from the review schema")


def _string(raw: object, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{field} MUST be a string")
    return raw


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{field} MUST be an integer")
    return raw


def _token(value: str, field: str) -> None:
    if _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a bounded portable token")


def _digest_value(value: str, field: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{field} MUST be a lowercase SHA-256 digest")


def _timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} MUST include a timezone")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rater-a", type=Path, required=True)
    parser.add_argument("--rater-b", type=Path, required=True)
    parser.add_argument("--tie-break", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = reduce_corpus_reviews(
            load_manifest(args.manifest),
            load_review(args.rater_a),
            load_review(args.rater_b),
            tie_break=None if args.tie_break is None else load_review(args.tie_break),
        )
    except ValueError as exc:
        print(f"chatops-quality-corpus-review: FAIL {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(receipt.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 1 if args.require_complete and not receipt.review_complete else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
