"""In-memory :class:`ToolExecutor` for tests + local development.

Captures every dispatch attempt in an append-only list so a test can
assert on the exact intent the executor produced (action type, tool ref,
arguments, labels). Idempotency is honored: a second dispatch for the
same ``idempotency_key`` returns the same receipt with
``already_existed=True`` and does NOT duplicate the recorded entry - this
mirrors the contract in
`docs/roadmap/decisioning/execution-model.md § 5.6 Tool call`.

This is the Day-1 binding: no real function runs. A fork swaps it for a
live adapter (a native Python registry, an MCP client, an HTTP callout).

Test hooks:

- ``seed_outcome(idempotency_key, receipt)`` - pre-seed the ledger so the
  next execute of that key short-circuits to ``already_existed``.
- ``next_error(exc)`` - one-shot error injection for the next call.
- ``force_outcome(outcome, *, rollback_succeeded=None, detail=None)`` -
  one-shot override for the next call's returned outcome, used to
  exercise ``STOPPED`` / ``FAILED`` / ``PRECONDITION_FAILED`` paths
  without a real tool.
"""

from __future__ import annotations

from itertools import count

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import (
    ToolCallOutcome,
    ToolCallReceipt,
    ToolCallRequest,
    ToolExecutor,
    ToolPromotionError,
)


class RecordingToolExecutor(ToolExecutor):
    """A fake tool executor that keeps every request in-memory.

    Tests treat it as the source of truth for "what tool would the
    delivery layer have invoked"; the executor never runs a real
    function.
    """

    def __init__(self) -> None:
        self._records: list[ToolCallRequest] = []
        self._by_key: dict[str, ToolCallReceipt] = {}
        self._counter = count(1)
        self._next_error: Exception | None = None
        self._forced_outcome: ToolCallReceipt | None = None

    async def execute(self, request: ToolCallRequest) -> ToolCallReceipt:
        # Promotion check mirrors the direct-API enforce-label rule.
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise ToolPromotionError(
                "enforce-mode tool call requires an explicit 'enforce' "
                "label (execution-model.md 5.6 promotion contract)"
            )

        # Idempotency: prior successful ledger hit wins.
        prior = self._by_key.get(request.idempotency_key)
        if prior is not None and prior.outcome in (
            ToolCallOutcome.SUCCEEDED,
            ToolCallOutcome.ALREADY_APPLIED,
        ):
            return ToolCallReceipt(
                outcome=ToolCallOutcome.ALREADY_APPLIED,
                receipt_ref=prior.receipt_ref,
                already_existed=True,
                detail=prior.detail,
            )

        # One-shot error injection.
        if self._next_error is not None:
            err, self._next_error = self._next_error, None
            raise err

        # One-shot forced outcome (STOPPED / FAILED / PRECONDITION_FAILED).
        if self._forced_outcome is not None:
            forced, self._forced_outcome = self._forced_outcome, None
            self._records.append(request)
            if forced.outcome is ToolCallOutcome.SUCCEEDED:
                self._by_key[request.idempotency_key] = forced
            return forced

        # Default happy-path.
        receipt_ref = f"artifact-{next(self._counter)}"
        receipt = ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref=receipt_ref,
            detail=f"recorded tool call for {request.action_type_name}",
        )
        self._by_key[request.idempotency_key] = receipt
        self._records.append(request)
        return receipt

    # ------------------------------------------------------------------
    # Test-only hooks
    # ------------------------------------------------------------------

    @property
    def records(self) -> tuple[ToolCallRequest, ...]:
        """Every dispatch call the executor made, in order."""
        return tuple(self._records)

    def find(self, idempotency_key: str) -> ToolCallRequest | None:
        for record in self._records:
            if record.idempotency_key == idempotency_key:
                return record
        return None

    def seed_outcome(self, idempotency_key: str, receipt: ToolCallReceipt) -> None:
        """Pre-seed the ledger so the next execute short-circuits."""
        self._by_key[idempotency_key] = receipt

    def next_error(self, exc: Exception) -> None:
        """Raise ``exc`` on the very next :meth:`execute` call."""
        self._next_error = exc

    def force_outcome(
        self,
        outcome: ToolCallOutcome,
        *,
        rollback_succeeded: bool | None = None,
        detail: str | None = None,
    ) -> None:
        """Force the very next :meth:`execute` call to return ``outcome``."""
        self._forced_outcome = ToolCallReceipt(
            outcome=outcome,
            receipt_ref=f"forced-{next(self._counter)}",
            rollback_succeeded=rollback_succeeded,
            detail=detail,
        )


__all__ = ["RecordingToolExecutor"]
