from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from scripts.evaluation.chatops_quality_corpus import HiddenCorpusManifest
from scripts.evaluation.chatops_quality_corpus_review import (
    CorpusRaterReview,
    CorpusReviewEntry,
    ReviewDecision,
    load_review,
    reduce_corpus_reviews,
)

_MANIFEST_DIGEST = "a" * 64
_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "evaluation"
    / "chatops_quality_corpus_review.py"
)


def _manifest() -> HiddenCorpusManifest:
    cases = tuple(
        SimpleNamespace(
            case_id=f"en-case-{index:03d}",
            label_commitment=f"{index + 1:064x}",
        )
        for index in range(500)
    )
    return cast(
        HiddenCorpusManifest,
        SimpleNamespace(
            corpus_id="chatops-hidden",
            corpus_version="v1",
            content_digest=_MANIFEST_DIGEST,
            cases=cases,
            review_protocol=SimpleNamespace(
                minimum_independent_raters=2,
                minimum_rater_agreement=0.8,
            ),
        ),
    )


def _review(
    rater_id: str,
    family: str,
    *,
    rejected: frozenset[int] = frozenset(),
    indexes: tuple[int, ...] = tuple(range(500)),
) -> CorpusRaterReview:
    return CorpusRaterReview(
        corpus_id="chatops-hidden",
        corpus_version="v1",
        manifest_digest=_MANIFEST_DIGEST,
        rater_id=rater_id,
        rater_family=family,
        reviewed_at="2026-08-28T00:00:00Z",
        entries=tuple(
            CorpusReviewEntry(
                case_id=f"en-case-{index:03d}",
                label_commitment=f"{index + 1:064x}",
                decision=(ReviewDecision.REJECT if index in rejected else ReviewDecision.ACCEPT),
                reason_code="label_mismatch" if index in rejected else "label_supported",
            )
            for index in indexes
        ),
    )


def test_two_distinct_raters_complete_agreement() -> None:
    receipt = reduce_corpus_reviews(
        _manifest(),
        _review("rater-a", "family-a"),
        _review("rater-b", "family-b"),
    )

    assert receipt.review_complete is True
    assert receipt.agreement_rate == 1.0
    assert receipt.accepted_count == 500
    assert receipt.rejected_count == 0
    rendered = json.dumps(receipt.to_dict())
    assert "rater-a" not in rendered
    assert "en-case-000" not in rendered


def test_disagreements_require_exact_third_family_tie_break() -> None:
    first = _review("rater-a", "family-a")
    second = _review("rater-b", "family-b", rejected=frozenset({1, 2}))

    incomplete = reduce_corpus_reviews(_manifest(), first, second)
    assert incomplete.review_complete is False
    assert incomplete.gaps == ("tie_break_required=2",)

    tie_break = _review(
        "rater-c",
        "family-c",
        rejected=frozenset({2}),
        indexes=(1, 2),
    )
    complete = reduce_corpus_reviews(
        _manifest(),
        first,
        second,
        tie_break=tie_break,
    )
    assert complete.review_complete is True
    assert complete.tie_break_count == 2
    assert complete.accepted_count == 499
    assert complete.rejected_count == 1


def test_low_agreement_and_identity_conflicts_fail_closed() -> None:
    first = _review("rater-a", "family-a")
    second = _review(
        "rater-b",
        "family-b",
        rejected=frozenset(range(101)),
    )
    receipt = reduce_corpus_reviews(_manifest(), first, second)
    assert receipt.review_complete is False
    assert receipt.agreement_rate == 0.798
    assert receipt.gaps[0].startswith("agreement_rate=")

    with pytest.raises(ValueError, match="distinct"):
        reduce_corpus_reviews(
            _manifest(),
            first,
            replace(second, rater_family="family-a"),
        )


def test_review_requires_exact_case_and_label_commitment_coverage() -> None:
    first = _review("rater-a", "family-a")
    second = _review("rater-b", "family-b")

    with pytest.raises(ValueError, match="every manifest case"):
        reduce_corpus_reviews(
            _manifest(),
            replace(first, entries=first.entries[:-1]),
            second,
        )
    changed = replace(
        first.entries[0],
        label_commitment="f" * 64,
    )
    with pytest.raises(ValueError, match="label commitment"):
        reduce_corpus_reviews(
            _manifest(),
            replace(first, entries=(changed, *first.entries[1:])),
            second,
        )


def test_review_file_requires_owner_only_permissions(tmp_path: Path) -> None:
    review = _review("rater-a", "family-a")
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
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
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)

    with pytest.raises(ValueError, match="owner-only"):
        load_review(path)


def test_direct_script_entrypoint_is_runnable() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        (sys.executable, str(_SCRIPT), "--help"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    assert "--tie-break" in completed.stdout
