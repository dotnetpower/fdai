"""HilChannel-backed ApprovalGate for the IRP coordinator (slide 18).

Bridges the IRP :class:`~fdai.core.irp.coordinator.ApprovalGate` seam onto
the existing :class:`~fdai.shared.providers.hil_channel.HilChannel` (the
same seam the risk gate uses for Teams / Slack Adaptive Cards). A proposal
is delivered as an approval card, then polled until a terminal decision or
the TTL stop-condition, so IRP approvals flow through the real HIL channel
instead of a bespoke back-channel.

Fail-closed: a channel error or an exhausted TTL maps to
:attr:`~fdai.core.irp.coordinator.ApprovalDecision.TIMEOUT` - the IRP
coordinator then takes no action. The gate never fabricates an approval.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from fdai.core.irp.coordinator import ApprovalDecision, MitigationProposal
from fdai.shared.providers.hil_channel import (
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilDecision,
)

_LOGGER = logging.getLogger(__name__)

_DECISION_MAP: dict[HilDecision, ApprovalDecision] = {
    HilDecision.APPROVE: ApprovalDecision.APPROVED,
    HilDecision.REJECT: ApprovalDecision.REJECTED,
    HilDecision.TIMEOUT: ApprovalDecision.TIMEOUT,
}


class HilChannelApprovalGate:
    """Route IRP proposals through the shared HIL channel seam."""

    __slots__ = ("_channel", "_interval", "_monotonic", "_sleeper", "_ttl")

    def __init__(
        self,
        *,
        channel: HilChannel,
        poll_interval_seconds: float = 5.0,
        ttl_seconds: int = 1800,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds MUST be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds MUST be positive")
        self._channel = channel
        self._interval = poll_interval_seconds
        self._ttl = ttl_seconds
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        # Wall-clock (monotonic) deadline, not a poll count: a slow ``poll``
        # would otherwise let the loop run for max_polls * (poll_time +
        # interval), far exceeding the declared TTL stop-condition.
        self._monotonic: Callable[[], float] = monotonic or time.monotonic

    async def request(self, proposal: MitigationProposal) -> ApprovalDecision:
        card = HilApprovalRequest(
            approval_id=proposal.proposal_id,
            correlation_id=f"irp:{proposal.alert_id}",
            action_id=proposal.proposal_id,
            action_type=proposal.remediation_ref or "irp.mitigation",
            rule_ids=proposal.citations,
            target_resource_ref=proposal.alert_id,
            blast_radius_summary=f"IRP mitigation for alert {proposal.alert_id}",
            reasons=(f"priority={proposal.priority.value}",),
            ttl_seconds=self._ttl,
        )
        try:
            receipt = await self._channel.send(card)
        except HilChannelError:
            _LOGGER.warning("irp_hil_send_failed", extra={"approval_id": card.approval_id})
            return ApprovalDecision.TIMEOUT

        max_polls = max(1, int(self._ttl / self._interval))
        deadline = self._monotonic() + self._ttl
        for _attempt in range(max_polls):
            if self._monotonic() >= deadline:
                return ApprovalDecision.TIMEOUT
            try:
                response = await self._channel.poll(receipt)
            except HilChannelError:
                _LOGGER.warning("irp_hil_poll_failed", extra={"approval_id": card.approval_id})
                return ApprovalDecision.TIMEOUT
            mapped = _DECISION_MAP.get(response.decision)
            if mapped is not None:
                return mapped
            # PENDING - wait then poll again, clamped so a sleep never
            # overshoots the TTL deadline.
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return ApprovalDecision.TIMEOUT
            await self._sleeper(min(self._interval, remaining))
        return ApprovalDecision.TIMEOUT


__all__ = ["HilChannelApprovalGate"]
