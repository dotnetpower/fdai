"""In-memory :class:`RemediationPrPublisher` for tests + local development.

Captures every publish call in an append-only list so a test can assert
on the exact intent the executor produced (title, body, patch, labels).
Idempotency is honored: a second publish for the same
``idempotency_key`` returns the same receipt with ``already_existed=True``
and does NOT duplicate the recorded entry - this matches the contract in
``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Remediation PR``.
"""

from __future__ import annotations

from itertools import count

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import (
    PublishReceipt,
    RemediationPr,
    RemediationPrPublisher,
)


class RecordingRemediationPrPublisher(RemediationPrPublisher):
    """A fake publisher that keeps every intent in-memory.

    Tests treat it as the source of truth for "what would the delivery
    layer have posted"; the executor never sees a raw HTTP client.

    Bounded mode: pass ``max_records`` to cap the retained history and
    dedupe cache. Required for long-running dev pumps
    (:class:`~fdai.delivery.operator_api.streaming.live_control_loop.ControlLoopLiveEmitter`);
    tests leave it ``None`` for the historical unbounded semantics.
    """

    def __init__(self, *, max_records: int | None = None) -> None:
        if max_records is not None and max_records < 1:
            raise ValueError("max_records MUST be >= 1 when set")
        self._max_records = max_records
        self._records: list[RemediationPr] = []
        self._by_key: dict[str, PublishReceipt] = {}
        self._counter = count(1)

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        if pr.mode is not Mode.SHADOW:
            # The publisher rejects an enforce intent that has not been
            # promoted through the ActionType promotion_gate; the
            # executor MUST NOT rely on the publisher to allow it.
            if "enforce" not in pr.labels:
                raise ValueError(
                    "enforce-mode PR requires an explicit 'enforce' label (P1 promotion contract)"
                )

        prior = self._by_key.get(pr.idempotency_key)
        if prior is not None:
            return PublishReceipt(pr_ref=prior.pr_ref, url=prior.url, already_existed=True)

        pr_ref = f"pr-{next(self._counter)}"
        receipt = PublishReceipt(pr_ref=pr_ref, url=f"https://example.com/pr/{pr_ref}")
        self._by_key[pr.idempotency_key] = receipt
        self._records.append(pr)
        # Bounded mode: drop the oldest half in one shot when we cross
        # the cap. Also drop the corresponding dedupe keys so the two
        # structures stay coherent.
        cap = self._max_records
        if cap is not None and len(self._records) > cap:
            drop = len(self._records) - cap // 2
            dropped = self._records[:drop]
            del self._records[:drop]
            for old in dropped:
                self._by_key.pop(old.idempotency_key, None)
        return receipt

    # ------------------------------------------------------------------
    # Assertion helpers (test-only)
    # ------------------------------------------------------------------

    @property
    def records(self) -> tuple[RemediationPr, ...]:
        """Every publish call the executor made, in order."""
        return tuple(self._records)

    def find(self, idempotency_key: str) -> RemediationPr | None:
        for record in self._records:
            if record.idempotency_key == idempotency_key:
                return record
        return None


__all__ = ["RecordingRemediationPrPublisher"]
