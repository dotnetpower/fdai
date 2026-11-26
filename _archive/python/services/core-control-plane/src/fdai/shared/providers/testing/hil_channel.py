"""In-memory :class:`HilChannel` for unit tests + debugger sessions.

Ships in the main package (not under ``tests/``) so a fork MAY reuse
it as a lightweight backend for a local, throwaway environment. It is
**not** suitable for production - sent cards vanish on process
restart, and there is no real ChatOps substrate interaction.

Behavior matrix
---------------

The fake tracks every :meth:`HilChannel.send` in an in-process list and
supports three test knobs:

- :attr:`InMemoryHilChannel.send_error` - if set, ``send`` raises it
  exactly once (then clears). Simulates a 4xx / webhook down.
- :attr:`InMemoryHilChannel.poll_error` - if set, ``poll`` raises it
  exactly once. Simulates a substrate glitch that trips the caller's
  fallback.
- :meth:`InMemoryHilChannel.record_response` - pre-programmes the
  :class:`HilResponse` a subsequent :meth:`poll` returns for one
  ``approval_id``. Without a recorded response, ``poll`` returns a
  fresh :data:`HilDecision.PENDING`.

The observable state (``sent`` list, ``poll_count`` per approval) is
exposed as attributes so tests can assert on it without reaching into
private members.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilDecision,
    HilResponse,
)


class InMemoryHilChannel(HilChannel):
    """Deterministic, in-memory :class:`HilChannel`.

    Every operation is synchronous under the hood; the ``async``
    signatures match the Protocol so callers exercise the real
    control-flow paths (``await``) unchanged.
    """

    def __init__(
        self,
        *,
        send_error: BaseException | None = None,
        poll_error: BaseException | None = None,
    ) -> None:
        self._send_error = send_error
        self._poll_error = poll_error

        # Observable state - deliberately public.
        self.sent: list[HilApprovalRequest] = []
        self.receipts: list[HilApprovalReceipt] = []
        self._responses: dict[str, HilResponse] = {}
        self.poll_count: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # Test knobs
    # ------------------------------------------------------------------

    def record_response(self, approval_id: str, response: HilResponse) -> None:
        """Pre-programme the terminal :class:`HilResponse` for one approval.

        ``response.approval_id`` MUST match ``approval_id``; the fake
        rejects a mismatched pair so a test cannot accidentally file a
        response under the wrong pending request.
        """
        if response.approval_id != approval_id:
            raise ValueError(
                f"response.approval_id={response.approval_id!r} != approval_id={approval_id!r}"
            )
        self._responses[approval_id] = response

    # ------------------------------------------------------------------
    # HilChannel Protocol
    # ------------------------------------------------------------------

    async def send(self, request: HilApprovalRequest) -> HilApprovalReceipt:
        if self._send_error is not None:
            error = self._send_error
            self._send_error = None
            raise error

        receipt = HilApprovalReceipt(
            approval_id=request.approval_id,
            channel_ref=f"fake:{uuid.uuid4()}",
            sent_at=datetime.now(tz=UTC),
        )
        self.sent.append(request)
        self.receipts.append(receipt)
        return receipt

    async def poll(self, receipt: HilApprovalReceipt) -> HilResponse:
        if self._poll_error is not None:
            error = self._poll_error
            self._poll_error = None
            raise error

        self.poll_count[receipt.approval_id] += 1
        prior = self._responses.get(receipt.approval_id)
        if prior is not None:
            return prior
        # No terminal decision yet - surface PENDING so the caller keeps
        # polling until TTL. Never a synthetic APPROVE / REJECT.
        return HilResponse(
            approval_id=receipt.approval_id,
            decision=HilDecision.PENDING,
        )


__all__ = ["InMemoryHilChannel"]
