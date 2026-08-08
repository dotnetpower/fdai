"""IaC review publisher Protocol - Wave A.4.

The Assurance Twin's ambient review path
([assurance-twin.md](../../../../docs/roadmap/operations/assurance-twin.md) 1) posts a
grounded Check onto an IaC pull request when the twin's projection
finds violations against the proposed diff. The seam is CSP-neutral:
``core/assurance_twin/review.py`` calls this Protocol only.

Real adapters (GitHub Checks API, Azure DevOps status hook) live in
``delivery/gitops_pr/`` (or a fork's equivalent) and never appear in
``core/``. The upstream ships this Protocol + an in-memory fake so
the review flow can be exercised end-to-end without a network round
trip.

Design invariants
-----------------

- **Publish, not mutate**: the publisher writes an annotation onto an
  existing PR / diff; it does NOT open, merge, or close a PR. The
  ``remediation_pr`` seam owns opening / labelling / closing changes.
- **Idempotent by ``review.review_key``**: a second call with the same
  key returns ``already_existed=True`` and MUST NOT post a duplicate
  Check. Redelivery is safe.
- **Read-only view of the twin**: the review carries findings computed
  against a scratch projection; the publisher does not re-evaluate.
- **No privileged identity in ``core/``**: the caller injects an
  authenticated adapter at composition time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.projection import Finding


@dataclass(frozen=True, slots=True)
class IacReview:
    """One ambient review to post onto an IaC PR.

    Ordered so an adapter can render the review verbatim without
    reaching back into the twin.
    """

    pr_ref: str
    """Opaque handle of the IaC pull request being reviewed.

    Format depends on the adapter (``owner/repo#123`` for GitHub, a
    numeric id for Azure DevOps). ``core/`` never parses this string.
    """

    review_key: str
    """Idempotency key. Same key on redelivery MUST NOT post a duplicate.

    Callers derive it from ``(pr_ref, finding-set hash, twin snapshot
    revision)`` so a re-run against the same projection is a no-op.
    """

    findings: tuple[Finding, ...]
    """Ordered evidence chain the caller wants surfaced on the PR."""

    verdict: str
    """Aggregate verdict tag from the twin (`clear` / `needs_review` /
    `blocked`). The publisher does not compute this - it renders what
    the twin decided."""

    mode: Mode
    """Whether the review posts as an authoritative Check (``enforce``)
    or as a shadow annotation that never gates a merge (``shadow``).

    Shadow reviews MUST be labelled as advisory by the adapter so a
    downstream reviewer cannot mistake them for a required check.
    """

    generated_at: str
    """ISO-8601 timestamp the twin recorded when it built the review."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs (correlation id, twin
    revision, ...). Never carries secrets."""


@dataclass(frozen=True, slots=True)
class ReviewReceipt:
    """Adapter-issued receipt for one review-publish attempt."""

    check_ref: str
    """Opaque handle for the posted Check / annotation."""

    url: str | None = None
    """Optional deep link a reviewer can open."""

    already_existed: bool = False
    """``True`` when the adapter detected a prior post with the same
    ``review_key`` and returned it unchanged. The caller MUST audit
    that path distinctly so redelivery is traceable."""


class IacReviewPublishError(RuntimeError):
    """Raised when an adapter refuses to post the review (transport
    error, 4xx from the review API, invariant violation).

    The upstream code paths catch this and abstain rather than
    retrying blindly - a review that cannot be posted is treated as
    "twin has no opinion" for the risk-gate contract.
    """


@runtime_checkable
class IacReviewPublisher(Protocol):
    """Post an ambient review onto an IaC PR."""

    async def publish(self, review: IacReview) -> ReviewReceipt:
        """Return a receipt for the publish attempt.

        Implementations MUST:

        - be **idempotent by ``review.review_key``** - a second call
          with the same key returns ``already_existed=True`` and MUST
          NOT post a duplicate Check;
        - label ``shadow`` reviews as advisory so the CI provider does
          not gate a merge on them;
        - raise :class:`IacReviewPublishError` on any transport or
          policy failure; the caller treats a raise as "abstain".
        """
        ...


__all__ = [
    "IacReview",
    "IacReviewPublishError",
    "IacReviewPublisher",
    "ReviewReceipt",
]
