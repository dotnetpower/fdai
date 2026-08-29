"""LoggingExemptionLifecycleNotifier - safe, network-free default notifier."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from fdai.rule_catalog.schema.exemption import load_exemption_from_mapping
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionLifecycleAction,
    ExemptionLifecycleDecision,
)
from fdai.shared.providers.exemption_lifecycle import (
    ExemptionLifecycleNotifier,
    LoggingExemptionLifecycleNotifier,
)


def _exemption() -> object:
    return load_exemption_from_mapping(
        {
            "schema_version": "1.0.0",
            "id": "e.soon",
            "rule_id": "rule-a",
            "scope": {
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-a",
            },
            "justification": "Waived while a migration is being completed for this scope.",
            "requested_by": "00000000-0000-0000-0000-000000000001",
            "approved_by": "00000000-0000-0000-0000-000000000002",
            "state": "active",
            "created_at": "2026-08-01T00:00:00Z",
            "expires_at": "2026-08-25T00:00:00Z",
        }
    )


def test_logging_notifier_satisfies_the_protocol() -> None:
    assert isinstance(LoggingExemptionLifecycleNotifier(), ExemptionLifecycleNotifier)


@pytest.mark.asyncio
async def test_logging_notifier_logs_without_raising(caplog: pytest.LogCaptureFixture) -> None:
    exemption = _exemption()
    decision = ExemptionLifecycleDecision(
        exemption_id=exemption.id,  # type: ignore[attr-defined]
        rule_id=exemption.rule_id,  # type: ignore[attr-defined]
        action=ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY,
        expires_at=datetime(2026, 8, 25, tzinfo=UTC),
        at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    notifier = LoggingExemptionLifecycleNotifier()

    with caplog.at_level(logging.WARNING, logger="fdai.governance.exemption_lifecycle"):
        await notifier.notify_ahead_of_expiry(exemption=exemption, decision=decision)  # type: ignore[arg-type]

    assert any("exemption_ahead_of_expiry" in record.message for record in caplog.records)
