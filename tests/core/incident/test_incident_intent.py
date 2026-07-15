"""Chat intent tests for the built-in incident workflow."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.incident.intent import prepare_incident_chat
from fdai.shared.contracts.models import IncidentSeverity


def test_korean_request_becomes_confirmation_proposal() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)

    turn = prepare_incident_chat(
        "prod-api-01 대상으로 SEV2 장애 케이스 열어줘",
        requested_by="operator@example.com",
        now=now,
    )

    assert turn.status == "awaiting_confirmation"
    assert turn.proposal is not None
    assert turn.proposal.severity is IncidentSeverity.SEV2
    assert turn.proposal.correlation_keys == ("resource:prod-api-01",)
    assert turn.proposal.requested_by == "operator@example.com"
    assert "확인하면 생성" in turn.response


def test_missing_details_asks_instead_of_proposing() -> None:
    turn = prepare_incident_chat("장애 케이스 생성해줘", requested_by="operator@example.com")

    assert turn.status == "needs_details"
    assert turn.proposal is None
    assert "severity" in turn.response
    assert "target" in turn.response


def test_non_incident_command_is_not_misclassified() -> None:
    turn = prepare_incident_chat(
        "prod-api-01 서비스를 재시작해줘",
        requested_by="operator@example.com",
    )

    assert turn.status == "not_incident"
    assert turn.proposal is None