"""Tests for :class:`InMemoryHilChannel` fake."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aiopspilot.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
    HilDecision,
    HilResponse,
)
from aiopspilot.shared.providers.testing.hil_channel import InMemoryHilChannel


def _request(approval_id: str = "appr-1") -> HilApprovalRequest:
    return HilApprovalRequest(
        approval_id=approval_id,
        correlation_id=f"corr-{approval_id}",
        action_id="00000000-0000-0000-0000-000000000001",
        action_type="remediate.tag-missing-owner",
        rule_ids=("example.tag.owner-required",),
        target_resource_ref="resource:example/rg/vm-1",
        blast_radius_summary="1 resource",
        reasons=("action_type_in_shadow_mode",),
    )


async def test_fake_implements_protocol() -> None:
    channel = InMemoryHilChannel()
    assert isinstance(channel, HilChannel)


async def test_send_records_request_and_returns_receipt() -> None:
    channel = InMemoryHilChannel()
    receipt = await channel.send(_request())

    assert receipt.approval_id == "appr-1"
    assert receipt.channel_ref.startswith("fake:")
    assert receipt.sent_at.tzinfo is not None
    assert len(channel.sent) == 1
    assert channel.sent[0].approval_id == "appr-1"
    assert channel.receipts == [receipt]


async def test_poll_returns_pending_without_recorded_response() -> None:
    channel = InMemoryHilChannel()
    receipt = await channel.send(_request())
    response = await channel.poll(receipt)

    assert response.decision is HilDecision.PENDING
    assert response.approval_id == "appr-1"
    assert channel.poll_count["appr-1"] == 1


async def test_poll_returns_recorded_response() -> None:
    channel = InMemoryHilChannel()
    receipt = await channel.send(_request())
    approved = HilResponse(
        approval_id="appr-1",
        decision=HilDecision.APPROVE,
        approver_id="oid-abc",
        received_at=datetime.now(tz=UTC),
        reason="looks good",
    )
    channel.record_response("appr-1", approved)

    response = await channel.poll(receipt)
    assert response is approved
    # Repeated poll returns the same terminal value.
    assert await channel.poll(receipt) is approved
    assert channel.poll_count["appr-1"] == 2


def test_record_response_rejects_mismatched_id() -> None:
    channel = InMemoryHilChannel()
    with pytest.raises(ValueError, match="approval_id"):
        channel.record_response(
            "appr-1",
            HilResponse(approval_id="different", decision=HilDecision.APPROVE),
        )


async def test_send_error_fires_once() -> None:
    err = HilChannelError("simulated", approval_id="appr-1")
    channel = InMemoryHilChannel(send_error=err)

    with pytest.raises(HilChannelError):
        await channel.send(_request())

    # Second send succeeds — the injected error clears after one raise.
    receipt = await channel.send(_request())
    assert receipt.approval_id == "appr-1"


async def test_poll_error_fires_once() -> None:
    err = HilChannelError("simulated", approval_id="appr-1")
    channel = InMemoryHilChannel(poll_error=err)
    receipt = HilApprovalReceipt(
        approval_id="appr-1",
        channel_ref="fake:1",
        sent_at=datetime.now(tz=UTC),
    )
    with pytest.raises(HilChannelError):
        await channel.poll(receipt)

    # Second poll runs cleanly and returns PENDING.
    response = await channel.poll(receipt)
    assert response.decision is HilDecision.PENDING
