"""Action-bound evidence tests for the correlation trace projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fdai_operator_service.postgres import (
    TRACE_RECORD_LIMIT,
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_sql import AUDIT_TRACE_SQL
from fdai_operator_service.projection_logic import rule_fire_trace
from fdai_operator_service.projections import ProjectionUnavailableError


def test_trace_preserves_action_attempt_and_execution_outcome() -> None:
    trace = rule_fire_trace(
        "correlation-1",
        [
            {
                "seq": 1,
                "event_id": "event-1",
                "correlation_id": "source-correlation-1",
                "recorded_at": "2026-09-14T03:00:00Z",
                "actor": "Thor",
                "action_kind": "executor.remote.awaiting_effect_evidence",
                "mode": "enforce",
                "entry_hash": "hash-1",
                "previous_hash": "hash-0",
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
    assert trace["trace_kind"] == "decision"
    assert trace["source_authority"] == "operator-audit-log"
    assert trace["complete"] is True
    assert trace["first_recorded_at"] == "2026-09-14T03:00:00Z"
    assert trace["last_recorded_at"] == "2026-09-14T03:00:00Z"
    assert trace["latest_sequence"] == 1
    assert trace["latest_actor"] == "Thor"
    assert trace["latest_action_kind"] == "executor.remote.awaiting_effect_evidence"
    assert trace["latest_outcome"] == "awaiting_effect_evidence"
    assert trace["action_attempt_count"] == 1
    assert trace["effect_observation_count"] == 0
    assert trace["steps"] == [
        {
            "seq": 1,
            "event_id": "event-1",
            "source_correlation_id": "source-correlation-1",
            "recorded_at": "2026-09-14T03:00:00Z",
            "actor": "Thor",
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
            "previous_hash": "hash-0",
        }
    ]


def test_trace_does_not_invent_missing_action_identity() -> None:
    trace = rule_fire_trace(
        "correlation-1",
        [
            {
                "seq": 1,
                "event_id": "event-1",
                "correlation_id": None,
                "recorded_at": "2026-09-14T03:00:00Z",
                "actor": "Saga",
                "action_kind": "notification.route",
                "mode": "shadow",
                "entry_hash": "hash-1",
                "previous_hash": "hash-0",
                "entry": {"outcome": "failed"},
            }
        ],
    )

    assert trace is not None
    assert trace["steps"][0]["event_id"] == "event-1"
    assert trace["steps"][0]["source_correlation_id"] is None
    assert trace["steps"][0]["action_id"] is None
    assert trace["steps"][0]["attempt"] is None
    assert trace["steps"][0]["execution_path"] is None


def test_trace_rejects_conflicting_stage_fields() -> None:
    with pytest.raises(ValueError, match="stage fields conflict"):
        rule_fire_trace(
            "correlation-1",
            [
                {
                    "seq": 1,
                    "event_id": "event-1",
                    "correlation_id": "correlation-1",
                    "recorded_at": "2026-09-14T03:00:00Z",
                    "actor": "Forseti",
                    "action_kind": "risk_gate.unified",
                    "mode": "shadow",
                    "entry_hash": "hash-1",
                    "previous_hash": "hash-0",
                    "entry": {
                        "pipeline_stage": "gate",
                        "stage": "execute",
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    ("entry_attempt", "workflow_attempt", "message"),
    [
        (1, 2, "attempt fields conflict"),
        (0, 2, "attempt MUST be positive"),
        (1, 0, "attempt MUST be positive"),
    ],
)
def test_trace_rejects_invalid_or_conflicting_attempt_identity(
    entry_attempt: int,
    workflow_attempt: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        rule_fire_trace(
            "correlation-1",
            [
                {
                    "seq": 1,
                    "event_id": "event-1",
                    "correlation_id": "correlation-1",
                    "recorded_at": "2026-09-14T03:00:00Z",
                    "actor": "Thor",
                    "action_kind": "executor.remote.dispatched",
                    "mode": "enforce",
                    "entry_hash": "hash-1",
                    "previous_hash": "hash-0",
                    "entry": {
                        "attempt": entry_attempt,
                        "workflow_action": {"attempt": workflow_attempt},
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"stage": 3}, "stage MUST be a non-empty string or null"),
        ({"decision": " "}, "decision MUST be a non-empty string or null"),
        ({"reason": False}, "reason MUST be a non-empty string or null"),
        ({"action_id": []}, "action_id MUST be a non-empty string or null"),
        ({"execution_path": {}}, "execution_path MUST be a non-empty string or null"),
        ({"outcome": 1}, "outcome MUST be a non-empty string or null"),
        ({"attempt": "2"}, "attempt MUST be an integer or null"),
        ({"workflow_action": []}, "workflow_action MUST be an object or null"),
        (
            {"workflow_action": {"attempt": "2"}},
            "attempt MUST be an integer or null",
        ),
    ],
)
def test_trace_rejects_malformed_optional_evidence(
    entry: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        rule_fire_trace(
            "correlation-1",
            [
                {
                    "seq": 1,
                    "event_id": "event-1",
                    "correlation_id": "correlation-1",
                    "recorded_at": "2026-09-14T03:00:00Z",
                    "actor": "Thor",
                    "action_kind": "executor.remote.dispatched",
                    "mode": "enforce",
                    "entry_hash": "hash-1",
                    "previous_hash": "hash-0",
                    "entry": entry,
                }
            ],
        )


class _TraceRowsModel(PostgresOperatorReadModel):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(PostgresOperatorReadModelConfig(dsn="postgresql://example.invalid/db"))
        self.rows = rows
        self.parameters: Mapping[str, object] | None = None

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        assert statement == AUDIT_TRACE_SQL
        self.parameters = parameters
        return self.rows


@pytest.mark.asyncio
async def test_trace_rejects_more_records_than_the_projection_limit() -> None:
    model = _TraceRowsModel([{} for _ in range(TRACE_RECORD_LIMIT + 1)])

    with pytest.raises(ProjectionUnavailableError, match="exceeds the 500-record"):
        await model.get_rule_fire_trace("correlation-1")

    assert model.parameters == {
        "correlation_id": "correlation-1",
        "fetch": TRACE_RECORD_LIMIT + 1,
    }


@pytest.mark.asyncio
async def test_trace_reader_reports_conflicting_stage_fields_as_unavailable() -> None:
    model = _TraceRowsModel(
        [
            {
                "seq": 1,
                "event_id": "event-1",
                "correlation_id": "correlation-1",
                "actor": "Forseti",
                "action_kind": "risk_gate.unified",
                "mode": "shadow",
                "entry": {"pipeline_stage": "gate", "stage": "execute"},
                "previous_hash": "hash-0",
                "entry_hash": "hash-1",
                "created_at": "2026-09-14T03:00:00Z",
            }
        ]
    )

    with pytest.raises(ProjectionUnavailableError, match="audit trace is malformed"):
        await model.get_rule_fire_trace("correlation-1")


@pytest.mark.asyncio
async def test_trace_reader_rejects_a_non_object_audit_entry() -> None:
    model = _TraceRowsModel(
        [
            {
                "seq": 1,
                "event_id": "event-1",
                "correlation_id": "correlation-1",
                "actor": "Forseti",
                "action_kind": "risk_gate.unified",
                "mode": "shadow",
                "entry": [],
                "previous_hash": "hash-0",
                "entry_hash": "hash-1",
                "created_at": "2026-09-14T03:00:00Z",
            }
        ]
    )

    with pytest.raises(ProjectionUnavailableError, match="trace entry is malformed"):
        await model.get_rule_fire_trace("correlation-1")


def test_trace_query_joins_executor_rows_through_correlated_event_ids() -> None:
    assert "correlation_id = %(correlation_id)s::text" in AUDIT_TRACE_SQL
    assert "event_id IN (SELECT event_id FROM correlated_events)" in AUDIT_TRACE_SQL
    assert "LIMIT %(fetch)s" in AUDIT_TRACE_SQL
