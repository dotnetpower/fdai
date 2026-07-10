"""Tests for the HilChannel-backed IRP ApprovalGate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.investigation import Priority
from fdai.core.irp import ApprovalDecision, HilChannelApprovalGate, MitigationProposal
from fdai.shared.providers.hil_channel import HilChannelError, HilDecision, HilResponse
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel

_NOW = datetime(2026, 7, 10, 18, 45, tzinfo=UTC)


def _proposal() -> MitigationProposal:
    return MitigationProposal(
        proposal_id="prop-abc123",
        alert_id="alert-1",
        remediation_ref="aoai.increase_tpm_quota",
        detail="Raise TPM quota",
        priority=Priority.P1,
        approver_role="approver",
        citations=("http_429_rate=0.4",),
        requested_at=_NOW,
    )


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_approve_response_maps_to_approved() -> None:
    channel = InMemoryHilChannel()
    channel.record_response(
        "prop-abc123",
        HilResponse(approval_id="prop-abc123", decision=HilDecision.APPROVE),
    )
    gate = HilChannelApprovalGate(channel=channel, sleeper=_noop_sleep)

    decision = await gate.request(_proposal())

    assert decision is ApprovalDecision.APPROVED
    # The card was sent through the real channel seam.
    assert channel.sent and channel.sent[0].action_type == "aoai.increase_tpm_quota"


@pytest.mark.asyncio
async def test_reject_response_maps_to_rejected() -> None:
    channel = InMemoryHilChannel()
    channel.record_response(
        "prop-abc123",
        HilResponse(approval_id="prop-abc123", decision=HilDecision.REJECT),
    )
    gate = HilChannelApprovalGate(channel=channel, sleeper=_noop_sleep)

    assert await gate.request(_proposal()) is ApprovalDecision.REJECTED


@pytest.mark.asyncio
async def test_pending_until_ttl_maps_to_timeout() -> None:
    channel = InMemoryHilChannel()  # never records a terminal response
    gate = HilChannelApprovalGate(
        channel=channel,
        poll_interval_seconds=5.0,
        ttl_seconds=15,  # -> 3 polls
        sleeper=_noop_sleep,
    )

    decision = await gate.request(_proposal())

    assert decision is ApprovalDecision.TIMEOUT
    assert channel.poll_count["prop-abc123"] == 3


@pytest.mark.asyncio
async def test_send_error_fails_closed_to_timeout() -> None:
    channel = InMemoryHilChannel(
        send_error=HilChannelError("webhook down", approval_id="prop-abc123")
    )
    gate = HilChannelApprovalGate(channel=channel, sleeper=_noop_sleep)

    assert await gate.request(_proposal()) is ApprovalDecision.TIMEOUT


@pytest.mark.asyncio
async def test_poll_error_fails_closed_to_timeout() -> None:
    channel = InMemoryHilChannel(
        poll_error=HilChannelError("poll failed", approval_id="prop-abc123")
    )
    gate = HilChannelApprovalGate(channel=channel, sleeper=_noop_sleep)

    assert await gate.request(_proposal()) is ApprovalDecision.TIMEOUT
