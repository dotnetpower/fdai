"""In-memory :class:`IacReviewPublisher` for tests + local development.

Captures every publish call in an append-only list so a test can assert
on the exact review the Twin produced (findings, verdict, mode).
Idempotency is honored: a second publish for the same ``review_key``
returns the same receipt with ``already_existed=True`` and does NOT
duplicate the recorded entry - matching the contract in
``shared/providers/iac_review.py``.
"""

from __future__ import annotations

from itertools import count

from fdai.shared.providers.iac_review import (
    IacReview,
    IacReviewPublisher,
    IacReviewPublishError,
    ReviewReceipt,
)


class InMemoryIacReviewPublisher(IacReviewPublisher):
    """A fake publisher that keeps every review in-memory.

    Tests treat it as the source of truth for "what would the review
    adapter have posted"; the Twin never sees a raw HTTP client.
    """

    def __init__(self) -> None:
        self._records: list[IacReview] = []
        self._by_key: dict[str, ReviewReceipt] = {}
        self._counter = count(1)
        self._next_error: IacReviewPublishError | None = None

    async def publish(self, review: IacReview) -> ReviewReceipt:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err

        prior = self._by_key.get(review.review_key)
        if prior is not None:
            return ReviewReceipt(
                check_ref=prior.check_ref,
                url=prior.url,
                already_existed=True,
            )

        check_ref = f"check-{next(self._counter)}"
        receipt = ReviewReceipt(
            check_ref=check_ref,
            url=f"https://example.com/check/{check_ref}",
        )
        self._by_key[review.review_key] = receipt
        self._records.append(review)
        return receipt

    # ------------------------------------------------------------------
    # Test-only injection + assertion helpers
    # ------------------------------------------------------------------

    @property
    def records(self) -> tuple[IacReview, ...]:
        """Every publish call the Twin made, in order."""

        return tuple(self._records)

    def find(self, review_key: str) -> IacReview | None:
        for record in self._records:
            if record.review_key == review_key:
                return record
        return None

    def next_error(self, error: IacReviewPublishError) -> None:
        """Inject a one-shot error into the next :meth:`publish` call.

        Consumed on first use; subsequent calls behave normally. Lets a
        test exercise the abstain-on-publish-failure path without a
        network mock.
        """

        self._next_error = error


__all__ = ["InMemoryIacReviewPublisher"]
