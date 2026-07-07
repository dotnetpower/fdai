"""Wave A.4 - IacReviewPublisher seam + Assurance Twin review verb."""

from __future__ import annotations

import pytest

from aiopspilot.core.assurance_twin import (
    ReviewOutcome,
    publish_review,
)
from aiopspilot.shared.contracts.models import Mode
from aiopspilot.shared.providers.iac_review import (
    IacReview,
    IacReviewPublishError,
    ReviewReceipt,
)
from aiopspilot.shared.providers.projection import Finding, ResourceRef
from aiopspilot.shared.providers.testing.iac_review import InMemoryIacReviewPublisher


def _finding(rule: str = "r-1", ref: str = "vm-a", severity: str = "high") -> Finding:
    return Finding(
        rule_id=rule,
        resource=ResourceRef(resource_type="compute.vm", ref=ref),
        severity=severity,  # type: ignore[arg-type]
        reason="reason",
    )


# ---------------------------------------------------------------------------
# Fake publisher contract
# ---------------------------------------------------------------------------


async def test_fake_publish_records_review_and_returns_receipt() -> None:
    pub = InMemoryIacReviewPublisher()
    review = IacReview(
        pr_ref="owner/repo#1",
        review_key="k-1",
        findings=(_finding(),),
        verdict="blocked",
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
    )
    receipt = await pub.publish(review)
    assert isinstance(receipt, ReviewReceipt)
    assert receipt.already_existed is False
    assert receipt.check_ref.startswith("check-")
    assert pub.records == (review,)


async def test_fake_publish_is_idempotent_by_review_key() -> None:
    pub = InMemoryIacReviewPublisher()
    review = IacReview(
        pr_ref="owner/repo#1",
        review_key="k-1",
        findings=(_finding(),),
        verdict="blocked",
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
    )
    r1 = await pub.publish(review)
    r2 = await pub.publish(review)
    assert r1.check_ref == r2.check_ref
    assert r2.already_existed is True
    # Recorded only once.
    assert len(pub.records) == 1


async def test_fake_publish_next_error_raises_once() -> None:
    pub = InMemoryIacReviewPublisher()
    pub.next_error(IacReviewPublishError("transport"))
    review = IacReview(
        pr_ref="p",
        review_key="k-1",
        findings=(),
        verdict="clear",
        mode=Mode.SHADOW,
        generated_at="t",
    )
    with pytest.raises(IacReviewPublishError):
        await pub.publish(review)
    # Second call recovers.
    receipt = await pub.publish(review)
    assert receipt.already_existed is False


def test_fake_find_helper() -> None:
    pub = InMemoryIacReviewPublisher()
    assert pub.find("k-1") is None


# ---------------------------------------------------------------------------
# publish_review orchestrator
# ---------------------------------------------------------------------------


async def test_publish_review_posts_and_returns_posted_outcome() -> None:
    pub = InMemoryIacReviewPublisher()
    result = await publish_review(
        publisher=pub,
        pr_ref="owner/repo#1",
        review_key="k-1",
        findings=(_finding(),),
        verdict="blocked",
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
        metadata={"correlation_id": "abc"},
    )
    assert result.outcome is ReviewOutcome.POSTED
    assert result.receipt is not None
    assert result.receipt.check_ref.startswith("check-")
    assert result.error_message is None
    assert result.review is not None
    assert result.review.metadata == {"correlation_id": "abc"}


async def test_publish_review_idempotent_returns_already_posted() -> None:
    pub = InMemoryIacReviewPublisher()
    kwargs = dict(
        publisher=pub,
        pr_ref="owner/repo#1",
        review_key="k-1",
        findings=(_finding(),),
        verdict="blocked",
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
    )
    first = await publish_review(**kwargs)  # type: ignore[arg-type]
    second = await publish_review(**kwargs)  # type: ignore[arg-type]
    assert first.outcome is ReviewOutcome.POSTED
    assert second.outcome is ReviewOutcome.ALREADY_POSTED
    assert second.receipt is not None
    assert second.receipt.check_ref == first.receipt.check_ref  # type: ignore[union-attr]


async def test_publish_review_abstains_on_publisher_error() -> None:
    pub = InMemoryIacReviewPublisher()
    pub.next_error(IacReviewPublishError("checks-api 502"))
    result = await publish_review(
        publisher=pub,
        pr_ref="owner/repo#1",
        review_key="k-1",
        findings=(_finding(),),
        verdict="blocked",
        mode=Mode.SHADOW,
        generated_at="2026-07-07T00:00:00Z",
    )
    assert result.outcome is ReviewOutcome.PUBLISH_ERROR
    assert result.receipt is None
    assert result.error_message == "checks-api 502"
    # We still carry the review we attempted, for audit purposes.
    assert result.review is not None
    assert result.review.review_key == "k-1"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, missing",
    [
        (
            {
                "pr_ref": "",
                "review_key": "k-1",
                "findings": (),
                "verdict": "clear",
                "mode": Mode.SHADOW,
                "generated_at": "t",
            },
            "pr_ref",
        ),
        (
            {
                "pr_ref": "p",
                "review_key": "",
                "findings": (),
                "verdict": "clear",
                "mode": Mode.SHADOW,
                "generated_at": "t",
            },
            "review_key",
        ),
        (
            {
                "pr_ref": "p",
                "review_key": "k",
                "findings": (),
                "verdict": "",
                "mode": Mode.SHADOW,
                "generated_at": "t",
            },
            "verdict",
        ),
        (
            {
                "pr_ref": "p",
                "review_key": "k",
                "findings": (),
                "verdict": "clear",
                "mode": Mode.SHADOW,
                "generated_at": "",
            },
            "generated_at",
        ),
    ],
)
async def test_publish_review_rejects_empty_string_args(kwargs: dict, missing: str) -> None:
    pub = InMemoryIacReviewPublisher()
    with pytest.raises(ValueError, match=missing):
        await publish_review(publisher=pub, **kwargs)


async def test_shadow_mode_review_records_mode_on_the_intent() -> None:
    pub = InMemoryIacReviewPublisher()
    await publish_review(
        publisher=pub,
        pr_ref="p",
        review_key="k",
        findings=(),
        verdict="clear",
        mode=Mode.SHADOW,
        generated_at="t",
    )
    (recorded,) = pub.records
    assert recorded.mode is Mode.SHADOW


async def test_enforce_mode_review_records_mode_on_the_intent() -> None:
    pub = InMemoryIacReviewPublisher()
    await publish_review(
        publisher=pub,
        pr_ref="p",
        review_key="k",
        findings=(),
        verdict="clear",
        mode=Mode.ENFORCE,
        generated_at="t",
    )
    (recorded,) = pub.records
    assert recorded.mode is Mode.ENFORCE
