"""Focused tests for the protected Cost Governance review recorder."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.shared.providers.cost_governance_review import (
    CostPromotionReview,
    CostReviewDecision,
    CostReviewTargetKind,
)
from scripts.deployment.azure.record_cost_governance_review import (
    load_ready_cost_review_target,
    record_cost_promotion_review,
)

_NOW = datetime(2026, 9, 13, tzinfo=UTC)
_TARGETS = (
    ("package-activation", "cost-governance"),
    ("action-type", "remediate.remove-orphan-resource"),
    ("action-type", "remediate.right-size"),
    ("action-type", "remediate.set-retention-policy"),
    ("action-type", "remediate.tag-add"),
    ("workflow", "cost-aware-remediation"),
)


class _Store:
    def __init__(self) -> None:
        self.reviews: list[CostPromotionReview] = []

    async def append_cost_promotion_review(self, review: CostPromotionReview) -> bool:
        self.reviews.append(review)
        return True

    async def read_cost_promotion_reviews(
        self,
        *,
        campaign_id: str,
        revision_pin_digest: str,
        limit: int,
    ) -> tuple[CostPromotionReview, ...]:
        return tuple(self.reviews[:limit])


def _readiness(path: Path, *, ready: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "campaign_id": "cost-governance-w7-dev",
                "ready": ready,
                "revision_pin_digest": f"sha256:{'1' * 64}",
                "targets": [
                    {
                        "campaign_report_digest": f"sha256:{index + 2:064x}",
                        "decision": "ready-for-independent-review",
                        "target_id": target_id,
                        "target_kind": target_kind,
                    }
                    for index, (target_kind, target_id) in enumerate(_TARGETS)
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


async def test_recorder_appends_one_exact_authority_neutral_target(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    _readiness(readiness)
    target = load_ready_cost_review_target(
        readiness,
        target_kind=CostReviewTargetKind.ACTION_TYPE,
        target_id="remediate.right-size",
    )
    store = _Store()

    review, inserted = await record_cost_promotion_review(
        ready_target=target,
        request_id="cost-review-right-size-r1",
        reviewer_identity="github:reviewer-example",
        decision=CostReviewDecision.RECOMMEND,
        rationale="The exact campaign meets every review gate.",
        reviewed_at=_NOW,
        retention_days=400,
        evidence_refs=("workflow:123:1",),
        store=store,
    )

    assert inserted is True
    assert store.reviews == [review]
    assert review.target_id == "remediate.right-size"
    assert review.campaign_evidence_digest == (
        f"sha256:{hashlib.sha256(readiness.read_bytes()).hexdigest()}"
    )
    assert review.evidence_refs[-1] == f"campaign-report:{target.campaign_report_digest}"
    assert review.approval_authority is False
    assert review.execution_authority is False
    assert review.promotion_authority is False


def test_recorder_rejects_blocked_or_missing_targets(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    _readiness(readiness, ready=False)
    with pytest.raises(ValueError, match="campaign MUST be ready"):
        load_ready_cost_review_target(
            readiness,
            target_kind=CostReviewTargetKind.WORKFLOW,
            target_id="cost-aware-remediation",
        )

    _readiness(readiness)
    with pytest.raises(ValueError, match="appear exactly once"):
        load_ready_cost_review_target(
            readiness,
            target_kind=CostReviewTargetKind.ACTION_TYPE,
            target_id="remediate.not-shipped",
        )


def test_recorder_rejects_a_malformed_sibling_target(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    _readiness(readiness)
    document = json.loads(readiness.read_text(encoding="utf-8"))
    document["targets"][1]["decision"] = "blocked"
    readiness.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="target record is invalid"):
        load_ready_cost_review_target(
            readiness,
            target_kind=CostReviewTargetKind.PACKAGE_ACTIVATION,
            target_id="cost-governance",
        )


async def test_recorder_rejects_retention_below_campaign_floor(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    _readiness(readiness)
    target = load_ready_cost_review_target(
        readiness,
        target_kind=CostReviewTargetKind.PACKAGE_ACTIVATION,
        target_id="cost-governance",
    )

    with pytest.raises(ValueError, match="retention_days MUST be"):
        await record_cost_promotion_review(
            ready_target=target,
            request_id="cost-review-package-r1",
            reviewer_identity="github:reviewer-example",
            decision=CostReviewDecision.HOLD,
            rationale="The review remains held pending operator confirmation.",
            reviewed_at=_NOW,
            retention_days=89,
            evidence_refs=("workflow:123:1",),
            store=_Store(),
        )
