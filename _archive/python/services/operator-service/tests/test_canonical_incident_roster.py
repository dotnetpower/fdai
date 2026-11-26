from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_operator_service.incident_projection import incident_summary
from fdai_operator_service.postgres_sql import INCIDENT_CURRENT_PAGE_SQL, INCIDENT_PAGE_SQL
from fdai_service_contracts.incident_intervention import incident_target_ref


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
        "canonical_correlation_keys": ["resource:/subscriptions/example/resourceGroups/one"],
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
    assert summary["target_ref"] == incident_target_ref("/subscriptions/example/resourceGroups/one")


@pytest.mark.parametrize(
    "correlation_keys",
    (
        None,
        "resource:/subscriptions/example",
        [],
        ["resource:"],
        ["resource:" + "x" * 2_049],
        [
            "resource:/subscriptions/example/resourceGroups/one",
            "resource:/subscriptions/example/resourceGroups/two",
        ],
    ),
)
def test_summary_withholds_unusable_canonical_target(
    correlation_keys: object,
) -> None:
    row = _bounded_history_row()
    row["canonical_correlation_keys"] = correlation_keys

    summary = incident_summary([row])

    assert summary["target_ref"] is None
