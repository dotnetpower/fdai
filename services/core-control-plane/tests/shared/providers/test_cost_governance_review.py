"""Authority boundaries for Cost Governance independent review receipts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.shared.providers.cost_governance_review import (
    CostPromotionReview,
    CostReviewDecision,
    CostReviewTargetKind,
)

_NOW = datetime(2026, 9, 13, tzinfo=UTC)


def _review(**changes: object) -> CostPromotionReview:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "request_id": "cost-review-action-right-size-r1",
        "campaign_id": "cost-governance-w7-dev",
        "campaign_evidence_digest": f"sha256:{'0' * 64}",
        "revision_pin_digest": f"sha256:{'1' * 64}",
        "campaign_report_digest": f"sha256:{'2' * 64}",
        "target_kind": CostReviewTargetKind.ACTION_TYPE,
        "target_id": "remediate.right-size",
        "reviewer_identity": "github:reviewer-example",
        "decision": CostReviewDecision.RECOMMEND,
        "rationale": "The exact campaign meets every review gate.",
        "reviewed_at": _NOW,
        "evidence_refs": ("workflow:123:1", "attestation:review-ready"),
        "retention_until": _NOW + timedelta(days=400),
    }
    values.update(changes)
    return CostPromotionReview(**values)  # type: ignore[arg-type]


def test_review_is_content_addressed_and_authority_neutral() -> None:
    review = _review()

    assert review.review_id == review.digest
    assert review.digest.startswith("sha256:")
    assert review.to_mapping()["approval_authority"] is False
    assert review.to_mapping()["execution_authority"] is False
    assert review.to_mapping()["promotion_authority"] is False
    assert review.evidence_refs == ("workflow:123:1", "attestation:review-ready")


@pytest.mark.parametrize(
    "authority_field",
    ("approval_authority", "execution_authority", "promotion_authority"),
)
def test_review_rejects_every_authority_flag(authority_field: str) -> None:
    with pytest.raises(ValueError, match="authority flags MUST be False"):
        _review(**{authority_field: True})


def test_review_requires_one_canonical_target_and_exact_evidence() -> None:
    with pytest.raises(ValueError, match="package activation review MUST target"):
        _review(
            target_kind=CostReviewTargetKind.PACKAGE_ACTIVATION,
            target_id="remediate.right-size",
        )
    with pytest.raises(ValueError, match="revision_pin_digest MUST use"):
        _review(revision_pin_digest="latest")
    with pytest.raises(ValueError, match="retention MUST follow"):
        _review(retention_until=_NOW)


def test_target_or_decision_change_produces_a_distinct_review() -> None:
    review = _review()

    assert replace(review, target_id="remediate.tag-add").review_id != review.review_id
    assert replace(review, decision=CostReviewDecision.DENY).review_id != review.review_id
    assert (
        replace(review, campaign_evidence_digest=f"sha256:{'9' * 64}").review_id != review.review_id
    )
