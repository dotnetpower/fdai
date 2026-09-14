"""Action-bound evidence tests for the correlation trace projection."""

from __future__ import annotations

from fdai_operator_service.postgres_sql import AUDIT_TRACE_SQL
from fdai_operator_service.projection_logic import rule_fire_trace


def test_trace_preserves_action_attempt_and_execution_outcome() -> None:
    trace = rule_fire_trace(
        "correlation-1",
        [
            {
                "seq": 1,
                "recorded_at": "2026-09-14T03:00:00Z",
                "action_kind": "executor.remote.awaiting_effect_evidence",
                "mode": "enforce",
                "entry_hash": "hash-1",
                "entry": {
                    "action_id": "action-1",
                    "workflow_action": {"attempt": 2},
                    "execution_path": "direct_api",
                    "outcome": "awaiting_effect_evidence",
                    "stage": "execute",
                },
            }
        ],
    )

    assert trace is not None
    assert trace["steps"] == [
        {
            "seq": 1,
            "recorded_at": "2026-09-14T03:00:00Z",
            "stage": "execute",
            "decision": None,
            "reason": None,
            "action_kind": "executor.remote.awaiting_effect_evidence",
            "mode": "enforce",
            "action_id": "action-1",
            "attempt": 2,
            "execution_path": "direct_api",
            "outcome": "awaiting_effect_evidence",
            "entry_hash": "hash-1",
        }
    ]


def test_trace_does_not_invent_missing_action_identity() -> None:
    trace = rule_fire_trace(
        "correlation-1",
        [
            {
                "seq": 1,
                "recorded_at": "2026-09-14T03:00:00Z",
                "action_kind": "notification.route",
                "mode": "shadow",
                "entry_hash": "hash-1",
                "entry": {"outcome": "failed"},
            }
        ],
    )

    assert trace is not None
    assert trace["steps"][0]["action_id"] is None
    assert trace["steps"][0]["attempt"] is None
    assert trace["steps"][0]["execution_path"] is None


def test_trace_query_joins_executor_rows_through_correlated_event_ids() -> None:
    assert "correlation_id = %(correlation_id)s::text" in AUDIT_TRACE_SQL
    assert "event_id IN (SELECT event_id FROM correlated_events)" in AUDIT_TRACE_SQL
    assert "LIMIT %(fetch)s" in AUDIT_TRACE_SQL
