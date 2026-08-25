from __future__ import annotations

from datetime import UTC, datetime

from fdai_operator_service.incident_projection import incident_summary
from fdai_operator_service.postgres_sql import INCIDENT_CURRENT_PAGE_SQL, INCIDENT_PAGE_SQL


def _bounded_history_row() -> dict[str, object]:
    return {
        "seq": 101,
        "event_id": "event-101",
        "correlation_id": "correlation-1",
        "actor": "fdai.core.control_loop",
        "action_kind": "risk_gate.unified",
        "mode": "shadow",
        "entry": {"decision": "hil"},
        "entry_hash": "hash-101",
        "previous_hash": "hash-100",
        "created_at": datetime(2026, 8, 25, 1, 1, tzinfo=UTC),
        "normalized_correlation_id": "correlation-1",
        "canonical_incident_id": "incident-1",
        "canonical_incident_number": "INC-202608-0001",
        "canonical_ticket_id": "ticket-1",
        "canonical_opened_at": "2026-08-25T00:00:00+00:00",
        "canonical_lifecycle_state": "triaging",
        "group_last_seq": 101,
        "group_history_count": 101,
    }


def test_incident_queries_require_canonical_lifecycle_membership() -> None:
    assert "projection.has_canonical_incident" in INCIDENT_PAGE_SQL
    assert "projection.has_canonical_incident" in INCIDENT_CURRENT_PAGE_SQL


def test_summary_uses_durable_identity_outside_bounded_history() -> None:
    summary = incident_summary([_bounded_history_row()])

    assert summary["incident_id"] == "incident-1"
    assert summary["incident_number"] == "INC-202608-0001"
    assert summary["ticket_id"] == "ticket-1"
    assert summary["opened_at"] == "2026-08-25T00:00:00+00:00"
    assert summary["status"] == "in_progress"
    assert summary["status_source"] == "incident_lifecycle"
    assert summary["lifecycle_state"] == "triaging"
