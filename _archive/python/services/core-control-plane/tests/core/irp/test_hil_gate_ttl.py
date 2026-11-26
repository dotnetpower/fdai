"""H8: the IRP HIL gate honours a wall-clock TTL, not just a poll count.

A slow ``poll`` (network latency) would let a count-based loop run for
``max_polls * (poll_time + interval)`` seconds, far past the declared TTL
stop-condition. The monotonic deadline makes the TTL a hard ceiling.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.investigation import Priority
from fdai.core.irp import ApprovalDecision, HilChannelApprovalGate, MitigationProposal
from fdai.shared.providers.hil_channel import HilDecision, HilResponse

_NOW = datetime(2026, 7, 10, 18, 45, tzinfo=UTC)


def _proposal() -> MitigationProposal:
    return MitigationProposal(
        proposal_id="prop-ttl",
        alert_id="alert-ttl",
        remediation_ref="aoai.increase_tpm_quota",
        detail="Raise TPM quota",
        priority=Priority.P1,
        approver_role="approver",
        citations=(),
        requested_at=_NOW,
    )


async def _noop_sleep(_seconds: float) -> None:
    return None


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


class _SlowPollChannel:
    """A channel whose every ``poll`` advances the (fake) clock by ``advance``."""

    def __init__(self, clock: _Clock, *, advance: float) -> None:
        self._clock = clock
        self._advance = advance
        self.poll_count = 0

    async def send(self, card: object) -> str:
        return getattr(card, "approval_id", "prop-ttl")

    async def poll(self, receipt: str) -> HilResponse:
        self.poll_count += 1
        self._clock.t += self._advance
        return HilResponse(approval_id=receipt, decision=HilDecision.PENDING)


async def test_ttl_deadline_dominates_slow_polls() -> None:
    clock = _Clock()
    channel = _SlowPollChannel(clock, advance=20.0)  # each poll "costs" 20s
    gate = HilChannelApprovalGate(
        channel=channel,  # type: ignore[arg-type]
        poll_interval_seconds=5.0,
        ttl_seconds=15,  # count-based would allow 3 polls
        sleeper=_noop_sleep,
        monotonic=clock.now,
    )

    decision = await gate.request(_proposal())

    assert decision is ApprovalDecision.TIMEOUT
    # Wall-clock deadline (15s) is crossed by the first 20s poll, so the
    # gate stops after ONE poll instead of running the full count.
    assert channel.poll_count == 1
