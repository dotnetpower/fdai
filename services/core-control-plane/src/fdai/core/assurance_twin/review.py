"""Assurance Twin - ambient IaC PR review (Wave A.4, core glue).

Turns a set of :class:`~fdai.shared.providers.projection.Finding`
values into an :class:`~fdai.shared.providers.iac_review.IacReview`
and hands it to an injected :class:`IacReviewPublisher`. The Twin
computes the findings against a scratch projection (see ``projection.py``
and ``report.py``); this module is the thin publish surface that keeps
``core/`` free of any HTTP / Checks-API dependency.

Design invariants
-----------------

- **Publish, do not decide**: the review verb reads from a
  ``PostureAssessmentReport``-shaped input and posts what the twin
  already computed. It never re-evaluates a rule.
- **Idempotent**: the caller supplies a stable ``review_key``; the
  Protocol contract guarantees a duplicate call is a no-op with
  ``already_existed=True``.
- **Abstain-on-failure**: a publisher raise -> :class:`ReviewOutcome`
  is ``PUBLISH_ERROR``; the caller treats it as "twin has no opinion"
  and does NOT retry blindly. Retry policy is the delivery adapter's
  concern.
- **Read-only**: no rule catalog, no state store, no privileged
  identity are touched here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import (
    IacReview,
    IacReviewPublisher,
    IacReviewPublishError,
    ReviewReceipt,
)
from fdai.shared.providers.projection import Finding


class ReviewOutcome(StrEnum):
    """Truthful outcome of one ambient-review publish attempt."""

    POSTED = "posted"
    """The review landed as a fresh Check."""

    ALREADY_POSTED = "already_posted"
    """A prior post with the same ``review_key`` was returned unchanged."""

    PUBLISH_ERROR = "publish_error"
    """The publisher raised; the twin abstains."""


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Result of :func:`publish_review` - truthful, side-effect-free view."""

    outcome: ReviewOutcome
    receipt: ReviewReceipt | None = None
    error_message: str | None = None
    # Keep the review we tried to post so the caller can audit what it
    # attempted, regardless of outcome.
    review: IacReview | None = None


async def publish_review(
    *,
    publisher: IacReviewPublisher,
    pr_ref: str,
    review_key: str,
    findings: Sequence[Finding],
    verdict: str,
    mode: Mode,
    generated_at: str,
    metadata: Mapping[str, str] | None = None,
) -> ReviewResult:
    """Publish one ambient review through ``publisher``.

    Fails-closed: on any :class:`IacReviewPublishError` the outcome is
    ``PUBLISH_ERROR`` and the caller decides whether to escalate, drop,
    or retry on a later change signal. Never raises.
    """

    if not pr_ref:
        raise ValueError("pr_ref MUST be non-empty")
    if not review_key:
        raise ValueError("review_key MUST be non-empty")
    if not verdict:
        raise ValueError("verdict MUST be non-empty")
    if not generated_at:
        raise ValueError("generated_at MUST be non-empty")

    review = IacReview(
        pr_ref=pr_ref,
        review_key=review_key,
        findings=tuple(findings),
        verdict=verdict,
        mode=mode,
        generated_at=generated_at,
        metadata=dict(metadata or {}),
    )

    try:
        receipt = await publisher.publish(review)
    except IacReviewPublishError as exc:
        return ReviewResult(
            outcome=ReviewOutcome.PUBLISH_ERROR,
            error_message=str(exc),
            review=review,
        )

    outcome = ReviewOutcome.ALREADY_POSTED if receipt.already_existed else ReviewOutcome.POSTED
    return ReviewResult(outcome=outcome, receipt=receipt, review=review)


__all__ = [
    "ReviewOutcome",
    "ReviewResult",
    "publish_review",
]
