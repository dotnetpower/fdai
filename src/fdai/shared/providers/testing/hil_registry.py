"""In-memory :class:`HilApprovalRegistry` for tests + upstream Day-1 wiring.

Composition ships this recording fake so upstream tests exercise the
`list_hil` / `approve_hil` tools without a live queue. A fork wires the
concrete backend (Postgres HIL queue) via the same Protocol.

Test hooks:

- ``seed(items)`` - preload pending items so tests can assert on the
  list-then-approve happy path.
- ``mark_resolved(idempotency_key, decision, approver_oid)`` - move an
  item to a terminal state without exercising the tool (used by the
  ``already_resolved`` conflict tests).
- ``next_error(exc)`` - raise ``exc`` on the very next ``record_decision``
  call, mirroring the injection hook on the other recording fakes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from itertools import count

from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilApprovalRegistry,
    HilDecisionReceipt,
    HilItemAlreadyResolvedError,
    HilItemNotFoundError,
    HilPendingItem,
)


class InMemoryHilApprovalRegistry(HilApprovalRegistry):
    """Recording fake for the console + tests.

    The registry keeps two dicts:

    - ``_pending`` - pending items indexed by ``idempotency_key``.
    - ``_resolved`` - previously-recorded receipts indexed by the same
      key so an idempotent replay short-circuits.
    """

    def __init__(self) -> None:
        self._pending: dict[str, HilPendingItem] = {}
        self._resolved: dict[str, HilDecisionReceipt] = {}
        self._counter = count(1)
        self._next_error: Exception | None = None

    async def list_pending(self, *, limit: int = 50) -> Sequence[HilPendingItem]:
        if limit < 1:
            limit = 1
        # Deterministic order: newest requested first (falls back to
        # idempotency_key when requested_at is missing).
        ordered = sorted(
            self._pending.values(),
            key=lambda item: (
                item.requested_at or datetime.min.replace(tzinfo=UTC),
                item.idempotency_key,
            ),
            reverse=True,
        )
        return tuple(ordered[:limit])

    async def get_pending(self, idempotency_key: str) -> HilPendingItem | None:
        return self._pending.get(idempotency_key)

    async def get_pending_by_approval_id(
        self,
        approval_id: str,
    ) -> HilPendingItem | None:
        return next(
            (item for item in self._pending.values() if item.approval_id == approval_id),
            None,
        )

    async def get_decision_by_approval_id(
        self,
        approval_id: str,
    ) -> HilDecisionReceipt | None:
        for receipt in self._resolved.values():
            if receipt.approval_id == approval_id:
                return replace(receipt, already_recorded=True)
        return None

    async def record_decision(
        self,
        *,
        idempotency_key: str,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
        decided_at: datetime | None = None,
    ) -> HilDecisionReceipt:
        if self._next_error is not None:
            err, self._next_error = self._next_error, None
            raise err

        prior = self._resolved.get(idempotency_key)
        if prior is not None:
            if prior.decision is not decision:
                raise HilItemAlreadyResolvedError(
                    idempotency_key, prior_decision=prior.decision.value
                )
            # Same decision -> idempotent replay: return the receipt with
            # already_recorded=True so the console tool can audit the
            # replay path distinctly.
            return HilDecisionReceipt(
                approval_id=prior.approval_id,
                idempotency_key=prior.idempotency_key,
                decision=prior.decision,
                approver_oid=prior.approver_oid,
                decided_at=prior.decided_at,
                receipt_ref=prior.receipt_ref,
                already_recorded=True,
                justification=prior.justification,
                delivered=prior.delivered,
                delivery_attempts=prior.delivery_attempts,
                delivery_abandoned=prior.delivery_abandoned,
                last_delivery_error=prior.last_delivery_error,
            )

        pending = self._pending.get(idempotency_key)
        if pending is None:
            raise HilItemNotFoundError(idempotency_key)

        now = decided_at or datetime.now(tz=UTC)
        receipt = HilDecisionReceipt(
            approval_id=pending.approval_id,
            idempotency_key=idempotency_key,
            decision=decision,
            approver_oid=approver_oid,
            decided_at=now,
            receipt_ref=f"hil-receipt-{next(self._counter)}",
            already_recorded=False,
            justification=justification,
        )
        self._resolved[idempotency_key] = receipt
        # A resolved item is removed from pending so a subsequent
        # list_pending does not surface it.
        self._pending.pop(idempotency_key, None)
        return receipt

    async def list_undelivered(self, *, limit: int = 100) -> Sequence[HilDecisionReceipt]:
        receipts = tuple(
            receipt
            for receipt in self._resolved.values()
            if not receipt.delivered and not receipt.delivery_abandoned
        )
        return receipts[: max(1, limit)]

    async def record_delivery_attempt(
        self,
        *,
        idempotency_key: str,
        delivered: bool,
        error_code: str = "",
        max_attempts: int,
    ) -> HilDecisionReceipt:
        prior = self._resolved.get(idempotency_key)
        if prior is None:
            raise HilItemNotFoundError(idempotency_key)
        if max_attempts <= 0:
            raise ValueError("max_attempts MUST be positive")
        if prior.delivered or prior.delivery_abandoned:
            return prior
        attempts = prior.delivery_attempts + 1
        updated = replace(
            prior,
            delivered=delivered,
            delivery_attempts=attempts,
            delivery_abandoned=not delivered and attempts >= max_attempts,
            last_delivery_error="" if delivered else error_code,
        )
        self._resolved[idempotency_key] = updated
        return updated

    # ------------------------------------------------------------------
    # Test-only hooks
    # ------------------------------------------------------------------

    def seed(self, items: Sequence[HilPendingItem]) -> None:
        for item in items:
            self._pending[item.idempotency_key] = item

    def mark_resolved(
        self,
        idempotency_key: str,
        *,
        decision: HilApprovalDecision,
        approver_oid: str,
        justification: str = "",
    ) -> HilDecisionReceipt:
        """Directly record a decision without running through the
        tool - used by conflict-path tests."""
        pending = self._pending.get(idempotency_key)
        approval_id = pending.approval_id if pending else idempotency_key
        receipt = HilDecisionReceipt(
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            decision=decision,
            approver_oid=approver_oid,
            decided_at=datetime.now(tz=UTC),
            receipt_ref=f"hil-receipt-seed-{next(self._counter)}",
            already_recorded=False,
            justification=justification,
        )
        self._resolved[idempotency_key] = receipt
        self._pending.pop(idempotency_key, None)
        return receipt

    def next_error(self, exc: Exception) -> None:
        """Raise ``exc`` on the very next ``record_decision`` call."""
        self._next_error = exc

    @property
    def resolved(self) -> tuple[HilDecisionReceipt, ...]:
        """Every decision recorded, in insertion order."""
        return tuple(self._resolved.values())


__all__ = ["InMemoryHilApprovalRegistry"]
