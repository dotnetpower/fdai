"""In-memory :class:`PreflightCheckPublisher` for tests + local development.

Mirrors the shape of
:mod:`fdai.shared.providers.testing.iac_review` so the two
publisher fakes stay consistent.
"""

from __future__ import annotations

from itertools import count

from fdai.shared.providers.preflight_check import (
    PreflightCheck,
    PreflightCheckPublisher,
    PreflightCheckPublishError,
    PreflightCheckReceipt,
)


class InMemoryPreflightCheckPublisher(PreflightCheckPublisher):
    """Fake publisher that keeps every intent in-memory."""

    def __init__(self) -> None:
        self._records: list[PreflightCheck] = []
        self._by_key: dict[str, PreflightCheckReceipt] = {}
        self._counter = count(1)
        self._next_error: PreflightCheckPublishError | None = None

    async def publish(self, check: PreflightCheck) -> PreflightCheckReceipt:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err

        prior = self._by_key.get(check.check_key)
        if prior is not None:
            return PreflightCheckReceipt(
                check_ref=prior.check_ref,
                url=prior.url,
                already_existed=True,
            )

        check_ref = f"preflight-check-{next(self._counter)}"
        receipt = PreflightCheckReceipt(
            check_ref=check_ref,
            url=f"https://example.com/checks/{check_ref}",
        )
        self._by_key[check.check_key] = receipt
        self._records.append(check)
        return receipt

    # ------------------------------------------------------------------
    # Test-only helpers
    # ------------------------------------------------------------------

    @property
    def records(self) -> tuple[PreflightCheck, ...]:
        return tuple(self._records)

    def find(self, check_key: str) -> PreflightCheck | None:
        for record in self._records:
            if record.check_key == check_key:
                return record
        return None

    def next_error(self, error: PreflightCheckPublishError) -> None:
        """One-shot error injection for the abstain-on-publish-failure path."""

        self._next_error = error


__all__ = ["InMemoryPreflightCheckPublisher"]
