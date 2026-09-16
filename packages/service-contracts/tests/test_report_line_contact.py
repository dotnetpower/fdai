from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai_service_contracts import (
    ReportLineContactCommand,
    build_report_line_contact_command,
)

NOW = datetime(2026, 9, 16, 1, 0, tzinfo=UTC)


def test_report_line_contact_command_binds_exact_requester_choice() -> None:
    command = build_report_line_contact_command(
        approval_id="approval-1",
        requester_ref="PERSON-A",
        consent=True,
        expected_consent_revision=0,
        requested_at=NOW,
        idempotency_key="contact-1",
    )

    assert command.requester_ref == "person-a"
    assert command.approval_authority is False
    assert command.execution_authority is False


def test_report_line_contact_command_rejects_tampering() -> None:
    command = build_report_line_contact_command(
        approval_id="approval-1",
        requester_ref="person-a",
        consent=True,
        expected_consent_revision=0,
        requested_at=NOW,
        idempotency_key="contact-1",
    )

    with pytest.raises(ValueError, match="digest"):
        ReportLineContactCommand.model_validate(
            {**command.model_dump(mode="json"), "consent": False}
        )
