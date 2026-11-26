from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fdai.runtime.consumers import _consume_hil_decisions
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.testing import InMemoryEventBus
from fdai_service_contracts import build_report_line_contact_command


async def test_hil_consumer_routes_contact_consent_without_action_decision() -> None:
    bus = InMemoryEventBus()
    coordinator = AsyncMock()
    command = build_report_line_contact_command(
        approval_id="approval-1",
        requester_ref="person-a",
        consent=True,
        expected_consent_revision=0,
        requested_at=datetime(2026, 9, 16, 1, 0, tzinfo=UTC),
        idempotency_key="contact-1",
    )
    await bus.publish(
        "hil-decisions",
        command.approval_id,
        command.model_dump(mode="json"),
    )

    await _consume_hil_decisions(
        bus=bus,
        topic="hil-decisions",
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    coordinator.decide_report_line_contact.assert_awaited_once_with(
        approval_id="approval-1",
        requester_oid="person-a",
        consent=True,
        expected_consent_revision=0,
    )
    coordinator.resolve.assert_not_called()


def _recording_coordinator(receipts: dict[str, dict[str, object]]) -> AsyncMock:
    """Return a coordinator double that reads Operator receipts from ``receipts``."""
    coordinator = AsyncMock()

    async def _read(approval_id: str) -> dict[str, object] | None:
        return receipts.get(approval_id)

    coordinator.read_operator_decision_receipt.side_effect = _read
    return coordinator


def _decision(approval_id: str, decision: str, approver_oid: str) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "idempotency_key": f"park-key:{approval_id}",
        "decision": decision,
        "approver_oid": approver_oid,
        "receipt_ref": f"operator-receipt:{approval_id}",
        "decided_at": "2026-09-29T01:00:00+00:00",
    }


async def test_hil_consumer_forwards_only_a_mapping_development_attestation() -> None:
    bus = InMemoryEventBus()
    first = {
        **_decision("approval-1", "approve", "owner-1"),
        "justification": "Verified the exact development action.",
        "development_attestation": {"approval_id": "approval-1"},
    }
    second = {
        **_decision("approval-2", "approve", "owner-1"),
        "justification": "Verified the exact development action.",
        "development_attestation": "x",
    }
    coordinator = _recording_coordinator({"approval-1": first, "approval-2": second})
    await bus.publish("hil-decisions", "approval-1", first)
    await bus.publish("hil-decisions", "approval-2", second)

    await _consume_hil_decisions(
        bus=bus,
        topic="hil-decisions",
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    attestations = [
        call.kwargs["development_attestation"] for call in coordinator.resolve.await_args_list
    ]
    assert attestations == [{"approval_id": "approval-1"}]
    dead = [envelope.payload async for envelope in bus.subscribe("hil-decisions.dlq", "test")]
    assert [item["reason"] for item in dead] == [
        "hil_decision_receipt_refused:attestation_mismatch"
    ]


async def test_hil_consumer_routes_only_a_recorded_human_decision() -> None:
    bus = InMemoryEventBus()
    receipts: dict[str, dict[str, object]] = {}
    for index, decision in enumerate(("approve", "reject", "pending", "timeout", "bogus")):
        payload = _decision(f"approval-{index}", decision, "approver-1")
        receipts[f"approval-{index}"] = payload
        await bus.publish("hil-decisions", f"approval-{index}", payload)
    coordinator = _recording_coordinator(receipts)

    await _consume_hil_decisions(
        bus=bus,
        topic="hil-decisions",
        coordinator=coordinator,
        stop=asyncio.Event(),
    )

    routed = [call.kwargs["decision"] for call in coordinator.resolve.await_args_list]
    assert routed == [HilDecision.APPROVE, HilDecision.REJECT]
    dead = [envelope.payload async for envelope in bus.subscribe("hil-decisions.dlq", "test")]
    assert [item["payload"]["decision"] for item in dead] == ["pending", "timeout", "bogus"]
