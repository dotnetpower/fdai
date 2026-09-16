from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fdai.runtime.consumers import _consume_hil_decisions
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
