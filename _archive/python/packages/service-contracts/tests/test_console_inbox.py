from __future__ import annotations

import pytest
from fdai_service_contracts.console_inbox import CONSOLE_INBOX_PREFIX, ConsoleInboxRecord
from pydantic import ValidationError


def _record(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "inbox_id": "a" * 32,
        "category": "operational_alert",
        "trust_tier": "a2_operational_alert",
        "severity": "warn",
        "title": "Alert",
        "body": "Bounded body.",
        "correlation_id": "correlation-1",
        "audit_id": None,
        "recorded_at": "2026-10-29T00:00:00+00:00",
    }
    value.update(overrides)
    return value


def test_record_is_a_frozen_no_authority_a2_alert() -> None:
    record = ConsoleInboxRecord.model_validate(_record())

    assert CONSOLE_INBOX_PREFIX == "console-inbox:"
    assert record.execution_authority is False
    with pytest.raises(ValidationError):
        record.title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"execution_authority": True},
        {"trust_tier": "a1_hil_approval"},
        {"severity": "verbose"},
        {"inbox_id": "short"},
        {"title": " "},
        {"body": "x" * 4001},
        {"extra_field": "value"},
    ],
)
def test_record_rejects_authority_unknown_tier_oversize_and_extra_fields(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ConsoleInboxRecord.model_validate(_record(**overrides))
