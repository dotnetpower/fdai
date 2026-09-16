"""Focused tests for durable Process and automation blueprint projections."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.assurance_twin_posture_projection import GAP_MALFORMED
from fdai_operator_service.autonomy_measurement_projection import (
    validate_autonomy_measurement,
)
from fdai_operator_service.dashboard_source import (
    MEASUREMENT_KINDS,
    MEASUREMENT_ROW_LIMIT,
)
from fdai_operator_service.families.operations import (
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts import OperatorRole


class RecordingFallback:
    """Record delegated operations without supplying runtime data."""

    def __init__(self) -> None:
        self.operations: list[str] = []

    async def read(self, query: ProjectionQuery) -> dict[str, object]:
        self.operations.append(query.operation)
        return {"operation": query.operation}


def _query(
    operation: str,
    *,
    path: dict[str, str] | None = None,
    params: dict[str, tuple[str, ...]] | None = None,
) -> ProjectionQuery:
    return ProjectionQuery(
        operation=operation,
        principal_id="operator-a",
        path=path or {},
        params=params or {},
        limit=100,
        cursor=None,
        roles=frozenset({OperatorRole.READER}),
    )


async def test_process_list_and_journal_project_durable_rows(monkeypatch: Any) -> None:
    now = datetime(2026, 8, 27, tzinfo=UTC)
    process = {
        "process_id": "process-1",
        "workflow_ref": "architecture-review",
        "workflow_version": "1.0.0",
        "status": "succeeded",
        "current_step": "",
        "target_resource_id": "resource-1",
        "started_at": now,
        "updated_at": now,
        "correlation_id": "correlation-1",
        "revision": 2,
    }
    event = {
        "event_id": "event-1",
        "kind": "process.completed",
        "recorded_at": now,
        "correlation_id": "correlation-1",
        "causation_id": None,
        "step_id": "review",
        "attempt": 1,
        "payload": {"outcome": "succeeded"},
    }
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self
        calls.append((statement, parameters))
        if "SELECT event_id" in statement and "FROM process_event" in statement:
            return [event]
        if "FROM state_kv" in statement:
            return []
        return [process]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    listing = await reader.read(
        _query("process.list", params={"workflow_ref": ("architecture-review",)})
    )
    journal = await reader.read(_query("process.events", path={"process_id": "process-1"}))

    assert listing["source"] == "postgresql:process_runtime"
    assert listing["durable"] is True
    assert listing["items"][0]["id"] == "process-1"
    assert listing["items"][0]["has_view"] is False
    assert journal["process"]["revision"] == 2
    assert journal["events"] == [
        {
            "event_id": "event-1",
            "kind": "process.completed",
            "recorded_at": now.isoformat(),
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": "review",
            "attempt": 1,
            "payload": {"outcome": "succeeded"},
        }
    ]
    assert journal["planning"] is None
    assert journal["investigation"] is None
    assert journal["control"]["available"] is False  # type: ignore[index]
    assert calls[0][1] == ("architecture-review", "operator-a")


async def test_adaptive_process_journal_includes_investigation_room(
    monkeypatch: Any,
) -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    process = {
        "process_id": "adaptive-1",
        "workflow_ref": "adaptive-investigation",
        "workflow_version": "1.0.0",
        "status": "succeeded",
        "current_step": "",
        "target_resource_id": "resource-1",
        "started_at": now,
        "updated_at": now,
        "correlation_id": "correlation-1",
        "revision": 2,
    }
    digest_a = f"sha256:{'a' * 64}"
    digest_b = f"sha256:{'b' * 64}"
    events = [
        {
            "event_id": "created",
            "kind": "process.created",
            "recorded_at": now,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": None,
            "attempt": 1,
            "payload": {
                "record_type": "adaptive_created",
                "incident_id": "incident-1",
                "initial_frame_digest": digest_a,
                "initial_active_set_receipt_digest": digest_b,
                "initial_cost_model_digest": digest_b,
                "active_strategy_digest": digest_a,
                "challenger_strategy_digest": None,
                "budget": {
                    "max_rounds": 2,
                    "max_queries": 2,
                    "max_cost_units": 10,
                    "deadline_at": now.isoformat(),
                    "policy_digest": digest_b,
                },
            },
        }
    ]

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        if "SELECT event_id" in statement and "FROM process_event" in statement:
            return events
        if "FROM state_kv" in statement:
            return []
        return [process]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    journal = await reader.read(_query("process.events", path={"process_id": "adaptive-1"}))

    assert journal["investigation"]["read_only"] is True  # type: ignore[index]
    assert journal["investigation"]["round_count"] == 0  # type: ignore[index]


async def test_process_journal_rejects_revision_change_during_read(
    monkeypatch: Any,
) -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    process = {
        "process_id": "process-1",
        "workflow_ref": "adaptive-investigation",
        "workflow_version": "1.0.0",
        "status": "running",
        "current_step": "round-1",
        "target_resource_id": "resource-1",
        "started_at": now,
        "updated_at": now,
        "correlation_id": "correlation-1",
        "revision": 1,
    }
    process_reads = 0

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        nonlocal process_reads
        del self, parameters
        if "SELECT event_id" in statement and "FROM process_event" in statement:
            return []
        if "FROM state_kv" in statement:
            return []
        process_reads += 1
        return [{**process, "revision": process_reads}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    with pytest.raises(
        ProjectionUnavailableError,
        match="changed while",
    ):
        await reader.read(_query("process.events", path={"process_id": "process-1"}))


async def test_process_journal_projects_principal_scoped_authoritative_control(
    monkeypatch: Any,
) -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    process = {
        "process_id": "process-1",
        "workflow_ref": "review-workflow",
        "workflow_version": "1.0.0",
        "status": "waiting",
        "current_step": "wait_for_evidence",
        "target_resource_id": "resource-1",
        "started_at": now,
        "updated_at": now,
        "correlation_id": "correlation-1",
        "revision": 3,
    }
    events = [
        {
            "event_id": "created",
            "kind": "process.created",
            "recorded_at": now,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": None,
            "attempt": 1,
            "payload": {
                "resume": {
                    "mode": "shadow",
                    "context": {"requester.principal": "operator-a"},
                }
            },
        },
        {
            "event_id": "started",
            "kind": "step.started",
            "recorded_at": now,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": "wait_for_evidence",
            "attempt": 1,
            "payload": {},
        },
        {
            "event_id": "waiting",
            "kind": "step.waiting",
            "recorded_at": now,
            "correlation_id": "correlation-1",
            "causation_id": None,
            "step_id": "wait_for_evidence",
            "attempt": 1,
            "payload": {"step_kind": "wait", "reason": "waiting_for:evidence.updated"},
        },
    ]
    catalog = {
        "_revision": "catalog-7",
        "workflows": [
            {
                "name": "review-workflow",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "wait_for_evidence",
                        "kind": "wait",
                        "wait_for": "evidence.updated",
                        "timeout_seconds": 300,
                    }
                ],
            }
        ],
    }
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self
        calls.append((statement, parameters))
        if "SELECT event_id" in statement:
            return events
        if "FROM state_kv" in statement:
            return [{"value": catalog}]
        return [process]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    journal = await reader.read(_query("process.events", path={"process_id": "process-1"}))

    assert journal["control"]["available"] is True  # type: ignore[index]
    assert journal["control"]["principal_scoped"] is True  # type: ignore[index]
    assert journal["control"]["step"]["requirements"]["wait_for"] == "evidence.updated"  # type: ignore[index]
    assert {
        item["id"]
        for item in journal["control"]["permitted_transitions"]  # type: ignore[index]
    } == set()
    process_calls = [
        parameters for statement, parameters in calls if "process_runtime" in statement
    ]
    assert process_calls == [
        ("process-1", "operator-a"),
        ("process-1", "operator-a"),
    ]


async def test_process_projection_reads_durable_var_approval_state(
    monkeypatch: Any,
) -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    events = [
        {
            "kind": "approval.requested",
            "step_id": "approval",
            "attempt": 1,
            "payload": {"step_kind": "approval"},
        }
    ]
    approval = {
        "process_id": "process-1",
        "step_id": "approval",
        "attempt": 1,
        "requester_principal": "operator-a",
        "required_role": "approver",
        "quorum": 2,
        "no_self_approval": True,
        "timeout_seconds": 300,
        "requested_at": now.isoformat(),
        "expires_at": now.isoformat(),
        "slots": [
            {
                "approval_id": "approval-1",
                "idempotency_key": "approval-1:decision",
            }
        ],
        "state": "pending",
        "revision": 1,
    }
    statements: list[str] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        if "key = ANY" in statement:
            return [{"value": {"approver_oid": "operator-b", "decision": "approve"}}]
        return [{"value": approval}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    state = await reader._approval_state(  # noqa: SLF001 - focused owned-reader contract
        process_id="process-1",
        step_id="approval",
        events=events,
    )

    assert state is not None
    assert state["_external_decisions"] == [{"principal": "operator-b", "decision": "approve"}]
    assert any("key = ANY" in statement for statement in statements)


async def test_empty_automation_blueprint_table_is_authoritative(monkeypatch: Any) -> None:
    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        if "COUNT(*) AS proposed" in statement:
            return [
                {
                    "proposed": 0,
                    "accepted": 0,
                    "rejected": 0,
                    "expired": 0,
                    "materialized": 0,
                    "realized_usage": 0,
                }
            ]
        return []

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    result = await reader.read(_query("automation_blueprint.list"))

    assert result == {
        "source": "postgresql:automation_blueprint_candidate",
        "mutation_controls": False,
        "count": 0,
        "candidates": [],
        "metrics": {
            "proposed": 0,
            "accepted": 0,
            "rejected": 0,
            "expired": 0,
            "materialized": 0,
            "realized_usage": 0,
            "candidate_precision": 0.0,
            "acceptance_rate": 0.0,
        },
    }


async def test_nonempty_automation_blueprint_projection_is_bounded_and_read_only(
    monkeypatch: Any,
) -> None:
    expires_at = datetime(2026, 9, 13, tzinfo=UTC)
    statements: list[str] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        if "COUNT(*) AS proposed" in statement:
            return [
                {
                    "proposed": 2,
                    "accepted": 1,
                    "rejected": 0,
                    "expired": 0,
                    "materialized": 1,
                    "realized_usage": 5,
                }
            ]
        return [
            {
                "candidate_id": "candidate-1",
                "normalized_task_intent": "check inventory drift",
                "schedule_expression": "0 3 * * *",
                "resource_scope": "scope://subscription/example/resource-group/app",
                "delivery_intent": "audit-only",
                "required_tools": ["query_inventory"],
                "isolation_profile": {"network": "deny", "filesystem": "deny"},
                "estimated_cost_microusd": 250,
                "evidence_fingerprints": ["sha256:" + ("a" * 64)],
                "confidence": 0.9,
                "expires_at": expires_at,
                "state": "accepted",
                "enabled": False,
                "shadow_only": True,
                "mutation_tool_ids": [],
                "realized_usage_count": 0,
            }
        ]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    result = await reader.read(_query("automation_blueprint.list"))

    assert result == {
        "source": "postgresql:automation_blueprint_candidate",
        "mutation_controls": False,
        "count": 1,
        "candidates": [
            {
                "candidate_id": "candidate-1",
                "state": "accepted",
                "normalized_task_intent": "check inventory drift",
                "schedule_expression": "0 3 * * *",
                "resource_scope": "scope://subscription/example/resource-group/app",
                "delivery_intent": "audit-only",
                "required_tools": ["query_inventory"],
                "isolation_profile": {"network": "deny", "filesystem": "deny"},
                "estimated_cost_microusd": 250,
                "evidence_fingerprints": ["sha256:" + ("a" * 64)],
                "confidence": 0.9,
                "expires_at": expires_at.isoformat(),
                "enabled": False,
                "shadow_only": True,
                "mutation_tool_ids": [],
            }
        ],
        "metrics": {
            "proposed": 2,
            "accepted": 1,
            "rejected": 0,
            "expired": 0,
            "materialized": 1,
            "realized_usage": 5,
            "candidate_precision": 0.5,
            "acceptance_rate": 1.0,
        },
    }
    assert statements[0].rstrip().endswith("LIMIT 200")


async def test_autonomy_returns_truthful_empty_canonical_projection(
    monkeypatch: Any,
) -> None:
    observed_at = datetime(2026, 9, 12, tzinfo=UTC)

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self
        if "FROM audit_log" in statement:
            assert parameters == (list(MEASUREMENT_KINDS), MEASUREMENT_ROW_LIMIT + 1)
            return [{"cutoff_seq": 0, "window_end": observed_at, "records": []}]
        if parameters == ("measurement:dashboard-comparison:v1",):
            return []
        raise AssertionError(parameters)

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    result = await reader.read(_query("autonomy"))

    assert result["schema_version"] == "1.0.0"
    assert result["sample_size"] == 0
    assert result["source"] == {
        "name": "postgresql:operational_measurements",
        "kind": "measurement",
        "as_of": observed_at.isoformat(),
    }
    assert all(metric["value"] is None for metric in result["success"].values())
    assert result["comparison"] is None
    assert result["comparison_status"] == "not_published"


@pytest.mark.parametrize(
    "value",
    [
        {},
        {
            "schema_version": "1.0.0",
            "synthetic": True,
            "source": {
                "name": "fixture",
                "kind": "synthetic",
                "as_of": "2026-09-12T00:00:00+00:00",
            },
        },
        {
            "schema_version": "1.0.0",
            "synthetic": False,
            "source": {"name": "postgresql:audit_log", "kind": "audit", "as_of": None},
        },
    ],
)
def test_autonomy_rejects_noncanonical_projection(value: object) -> None:
    with pytest.raises(
        ProjectionUnavailableError,
        match="authoritative autonomy measurement projection is malformed",
    ):
        validate_autonomy_measurement(value)


@pytest.mark.parametrize(
    "value",
    [
        {
            "schema_version": "1.0.0",
            "synthetic": False,
            "source": {
                "name": "outcome-assurance-measurement",
                "kind": "measurement",
                "as_of": "2026-09-12T00:00:00+00:00",
            },
        },
        {
            "schema_version": "1.0.0",
            "synthetic": False,
            "window_days": 30,
            "sample_size": 1,
            "confidence": None,
            "source": {
                "name": "outcome-assurance-measurement",
                "kind": "measurement",
                "as_of": "2026-09-12T00:00:00+00:00",
            },
            "rules": {"active": 0, "candidates_30d": 0, "promoted_30d": 0},
            "success": {},
            "leading": {},
            "guards": [],
            "finalization": {
                "finalized_events": 1,
                "pending_events": 0,
                "adverse_events": 0,
            },
            "attribution": {
                "attributed_events": 0,
                "unattributed_events": 0,
                "coverage": None,
            },
            "verticals": [],
            "tier": {"mix": {}, "bands": {}},
            "trend": {},
        },
    ],
)
def test_autonomy_rejects_incomplete_or_inconsistent_envelope(value: object) -> None:
    with pytest.raises(
        ProjectionUnavailableError,
        match="authoritative autonomy measurement projection is malformed",
    ):
        validate_autonomy_measurement(value)


async def test_remaining_console_evidence_projects_durable_tables(
    monkeypatch: Any,
) -> None:
    now = datetime(2026, 8, 27, tzinfo=UTC)

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self
        if "GROUP BY state" in statement:
            return [{"state": "delivered", "count": 1}]
        if "FROM conversation_adapter_breaker" in statement:
            assert "GROUP BY mode ORDER BY mode" in statement
            return [{"mode": "open", "count": 2}, {"mode": "closed", "count": 1}]
        if "COUNT(*) AS delivery_count" in statement:
            return [
                {
                    "delivery_count": 1,
                    "duplicate_risk_count": 0,
                    "retry_count": 1,
                    "abandonment_count": 0,
                    "latency_count": 1,
                    "latency_average": 0.0,
                    "latency_p95": 0.0,
                    "attempt_count": 2,
                    "acknowledgement_count": 1,
                }
            ]
        if "COUNT(*) AS total" in statement and "FROM forecast_episode" in statement:
            return [
                {
                    "total": 0,
                    "closed": 0,
                    "open": 0,
                    "overdue": 0,
                    "abstained": 0,
                    "due_total": 0,
                    "due_closed": 0,
                }
            ]
        if "payload->>'label' AS label" in statement:
            return []
        if "FROM forecast_publication_outbox" in statement:
            assert statement.count("available_at <= now()") == 2
            assert "MIN(created_at)" in statement
            return [{"pending": 0, "dead_lettered": 0, "oldest_pending_at": None}]
        if "FROM operator_forecast_retention" in statement:
            return [{"pending": 2, "overdue": 3}]
        if "FROM operator_memory " in statement:
            assert parameters == ("resource", "resource", "resource-1", "resource-1")
            return [
                {
                    "id": "memory-1",
                    "scope_kind": "resource",
                    "scope_ref": "resource-1",
                    "category": "preference",
                    "body": "Prefer concise evidence.",
                    "source_event": "operator.confirmed",
                    "source_ref": "turn-1",
                    "author": "operator",
                    "approved_by": "approver",
                    "created_at": now,
                    "superseded_by": None,
                    "ttl_seconds": 0,
                }
            ]
        if "FROM memory_compaction_candidate" in statement:
            assert parameters == ("resource", "resource", "resource-1", "resource-1")
            return []
        if "FROM skill_source " in statement:
            return [
                {
                    "source_id": "source-1",
                    "kind": "repository",
                    "enabled": True,
                    "last_refresh_at": now,
                    "error_count": 0,
                    "last_error_kind": None,
                }
            ]
        if "runtime:detection-readiness" in statement:
            return []
        if "runtime:analyzer-finding-receipt" in statement:
            return []
        if "runtime:analyzer-tick-receipt" in statement:
            assert "ORDER BY updated_at DESC, key DESC" in statement
            return []
        if "runtime:detection-lifecycle" in statement:
            return []
        if "runtime:configuration-baseline" in statement:
            return []
        if "MAX(created_at)" in statement:
            return [{"observed_at": now}]
        raise AssertionError(statement)

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    delivery = await reader.read(_query("conversation-delivery"))
    forecast = await reader.read(_query("forecast-learning"))
    memory = await reader.read(
        _query(
            "operator-memory",
            params={"scope_kind": ("resource",), "scope_ref": ("resource-1",)},
        )
    )
    skills = await reader.read(_query("skills"))
    detection = await reader.read(_query("detection.readiness"))
    baselines = await reader.read(_query("configuration-baselines"))

    assert delivery["delivery_count"] == 1
    assert delivery["breaker_states"] == {"open": 2, "closed": 1}
    assert delivery["retry_count"] == 1
    assert delivery["acknowledgement_count"] == 1
    assert forecast["episodes"]["total"] == 0
    assert forecast["episodes"]["closure_completeness"] is None
    assert forecast["retention"] == {"pending": 2, "overdue": 3}
    assert memory["items"][0]["id"] == "memory-1"
    assert memory["items"][0]["active"] is True
    assert skills["installed_count"] == 0
    assert skills["diagnostics"][0]["status"] == "ready"
    assert skills["diagnostics"][0]["observed_at"] == now.isoformat()
    assert detection["target_count"] == 0
    assert detection["counts"]["unknown"] == 0
    assert detection["lifecycle"]["target_count"] == 0
    assert detection["analyzer_coverage"]["status"] == "unavailable"
    assert detection["analyzer_coverage"]["unavailable_reason"] == "receipt_absent"
    assert detection["analyzer_run"] is None
    assert detection["pod_lifecycle"]["target_count"] == 0
    assert baselines["baseline"]["version"] == "not-published"
    assert baselines["drift"]["verdict"] == "not-evaluated"
    assert baselines["performance"] is None


@pytest.mark.parametrize("retention", ([], [{"pending": -1, "overdue": 0}]))
async def test_forecast_retention_does_not_replace_missing_or_malformed_evidence_with_zero(
    monkeypatch: pytest.MonkeyPatch, retention: list[dict[str, object]]
) -> None:
    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        if "FROM operator_forecast_retention" in statement:
            return retention
        if "COUNT(*) AS total" in statement:
            return [
                {
                    "total": 0,
                    "closed": 0,
                    "open": 0,
                    "overdue": 0,
                    "abstained": 0,
                    "due_total": 0,
                    "due_closed": 0,
                }
            ]
        if "GROUP BY" in statement:
            return []
        return [{"pending": 0, "dead_lettered": 0, "oldest_pending_at": None}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )
    with pytest.raises(ProjectionUnavailableError):
        await reader.read(_query("forecast-learning"))


@pytest.mark.parametrize(
    ("due_total", "due_closed", "expected"),
    ((5, 4, 0.8), (0, 0, None), (3, 0, 0.0)),
)
async def test_forecast_summary_uses_due_cohort_and_recorded_outcome_provenance(
    monkeypatch: pytest.MonkeyPatch,
    due_total: int,
    due_closed: int,
    expected: float | None,
) -> None:
    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        if "FROM forecast_episode" in statement:
            assert "closure_reason" not in statement
            assert "AS due_total" in statement
            assert "AS due_closed" in statement
            assert "closure_due_at <= now()" in statement
            return [
                {
                    "total": 10,
                    "closed": 4,
                    "open": 6,
                    "overdue": 1,
                    "abstained": 2,
                    "due_total": due_total,
                    "due_closed": due_closed,
                }
            ]
        if "FROM operator_forecast_retention" in statement:
            return [{"pending": 0, "overdue": 0}]
        assert "FROM forecast_publication_outbox" in statement
        if "GROUP BY" in statement:
            assert "topic = 'object.forecast-outcome'" in statement
            assert "payload->>'miss_origin'" in statement
            return [{"label": "false_negative", "miss_origin": "pipeline", "count": 1}]
        return [{"pending": 0, "dead_lettered": 0, "oldest_pending_at": None}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )
    result = await reader.read(_query("forecast-learning"))
    assert result["episodes"]["closure_completeness"] == expected
    assert result["episodes"]["total"] == 10
    assert result["episodes"]["closed"] == 4
    assert result["outcomes"] == [
        {"label": "false_negative", "miss_origin": "pipeline", "count": 1}
    ]


@pytest.mark.parametrize("label", (None, ""))
async def test_forecast_summary_rejects_unlabeled_outcome_records(
    monkeypatch: pytest.MonkeyPatch, label: str | None
) -> None:
    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        if "FROM forecast_episode" in statement:
            return [
                {
                    "total": 1,
                    "closed": 1,
                    "open": 0,
                    "overdue": 0,
                    "abstained": 0,
                    "due_total": 1,
                    "due_closed": 1,
                }
            ]
        if "GROUP BY" in statement:
            return [{"label": label, "miss_origin": None, "count": 1}]
        return [{"pending": 0, "dead_lettered": 0, "oldest_pending_at": None}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )
    with pytest.raises(ProjectionUnavailableError, match="outcome label"):
        await reader.read(_query("forecast-learning"))


@pytest.mark.parametrize("mode", ("", "unexpected", None))
async def test_delivery_rejects_malformed_recorded_breaker_modes(
    monkeypatch: pytest.MonkeyPatch, mode: str | None
) -> None:
    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        if "FROM conversation_adapter_breaker" in statement:
            return [{"mode": mode, "count": 1}]
        return []

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"), RecordingFallback()
    )
    with pytest.raises(ProjectionUnavailableError, match="breaker mode"):
        await reader.read(_query("conversation-delivery"))


@pytest.mark.parametrize(
    ("scope_kind", "scope_ref"),
    (
        ("resource", "resource-example"),
        ("resource-group", None),
        (None, "group-example"),
        (None, None),
        ("resource", "resource'with-quote"),
    ),
)
async def test_memory_scope_filters_entries_and_compactions_before_limit(
    monkeypatch: pytest.MonkeyPatch,
    scope_kind: str | None,
    scope_ref: str | None,
) -> None:
    calls: list[str] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        assert parameters == (scope_kind, scope_kind, scope_ref, scope_ref)
        assert "WHERE (%s::text IS NULL OR scope_kind = %s)" in statement
        assert "AND (%s::text IS NULL OR scope_ref = %s)" in statement
        assert statement.index("WHERE ") < statement.index("LIMIT 100")
        if scope_ref is not None:
            assert scope_ref not in statement
        calls.append(statement)
        if "FROM operator_memory " in statement:
            return []
        assert "FROM memory_compaction_candidate " in statement
        return [
            {
                "candidate_id": "candidate-example",
                "scope_kind": scope_kind or "resource",
                "scope_ref": scope_ref or "resource-example",
                "category": "preference",
                "body": "Prefer bounded evidence.",
                "source_refs": ["memory-example"],
                "proposed_by_agent": "Mimir",
                "state": "pending",
                "reviewed_by": None,
                "review_reason": None,
            }
        ]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )
    params = {}
    if scope_kind is not None:
        params["scope_kind"] = (scope_kind,)
    if scope_ref is not None:
        params["scope_ref"] = (scope_ref,)
    result = await reader.read(_query("operator-memory", params=params))
    assert len(calls) == 2
    assert result["compactions"][0]["scope_kind"] == (scope_kind or "resource")
    assert result["compactions"][0]["scope_ref"] == (scope_ref or "resource-example")


@pytest.mark.parametrize(
    ("enabled", "refreshed", "error_count", "expected"),
    (
        (True, False, 0, "not-measured"),
        (True, True, 0, "ready"),
        (True, False, 1, "error"),
        (True, True, 1, "error"),
        (False, False, 0, "disabled"),
        (False, True, 1, "disabled"),
    ),
)
async def test_skill_source_readiness_requires_recorded_refresh(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    refreshed: bool,
    error_count: int,
    expected: str,
) -> None:
    observed_at = datetime(2026, 9, 17, tzinfo=UTC) if refreshed else None

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        assert "FROM skill_source " in statement
        return [
            {
                "source_id": "source-example",
                "kind": "github_repository",
                "enabled": enabled,
                "last_refresh_at": observed_at,
                "error_count": error_count,
                "last_error_kind": "rate_limited" if error_count else None,
            }
        ]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )
    result = await reader.read(_query("skills"))
    diagnostic = result["diagnostics"][0]
    assert diagnostic["status"] == expected
    assert diagnostic["observed_at"] == (
        observed_at.isoformat() if observed_at is not None else None
    )
    assert diagnostic["reason"] == (
        "rate_limited"
        if error_count
        else "source_refreshed"
        if refreshed
        else "source_refresh_not_recorded"
    )
    assert result["execution_eligibility"] is False
    assert result["mutation_controls"] is False


async def test_detection_readiness_includes_latest_analyzer_tick(
    monkeypatch: Any,
) -> None:
    now = datetime(2026, 9, 14, 3, 30, tzinfo=UTC)
    report: dict[str, object] = {
        "targets": 22,
        "findings": 0,
        "published": 0,
        "duplicates_suppressed": 0,
        "uncertain": 0,
        "unsupported_targets": [],
        "analyzer_errors": [],
        "publish_errors": [],
        "receipt_errors": [],
        "receipts": [],
        "target_resolution": {
            "configured": 0,
            "discovered": 22,
            "candidate_count": 35,
            "inventory_consulted": True,
            "source_complete": True,
            "skipped_reasons": ["unverified_state_fact"],
            "skipped_reason_counts": {"unverified_state_fact": 13},
            "truncated": False,
        },
        "readiness": {
            "scheduling": "local_loop",
            "target_discovery": "available",
            "metric_access": "available",
            "event_publication": "unverified",
            "metric_source_delays": {},
        },
        "trace_continuity": {
            "targets": 0,
            "scenarios": 0,
            "continuous": 0,
            "unknown": 0,
            "findings": 0,
            "published": 0,
            "publish_errors": [],
        },
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        if "runtime:analyzer-tick-receipt" in statement:
            assert "ORDER BY updated_at DESC, key DESC" in statement
            assert "LIMIT 500" in statement
            return [
                {
                    "value": {
                        "schema_version": "1.2.0",
                        "run_id": "local-analyzer-1",
                        "tick_id": "0",
                        "attempt_id": digest,
                        "recorded_at": now.isoformat(),
                        "report_digest": digest,
                        "report": report,
                        "execution_authority": False,
                    },
                    "updated_at": now,
                }
            ]
        if "runtime:detection-readiness" in statement:
            return []
        if "runtime:analyzer-finding-receipt" in statement:
            return []
        if "runtime:detection-lifecycle" in statement:
            return []
        raise AssertionError(statement)

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    detection = await reader.read(_query("detection.readiness"))

    assert detection["observed_at"] == now.isoformat()
    assert detection["analyzer_run"]["candidate_count"] == 35  # type: ignore[index]
    assert detection["analyzer_run"]["targets"] == 22  # type: ignore[index]
    assert detection["analyzer_run"]["findings"] == 0  # type: ignore[index]
    assert detection["analyzer_run"]["source_complete"] is True  # type: ignore[index]
    assert detection["analyzer_run"]["analyzer_error_count"] == 0  # type: ignore[index]
    assert detection["analyzer_run"]["trace_publish_error_count"] == 0  # type: ignore[index]
    assert detection["analyzer_coverage"]["status"] == "unavailable"  # type: ignore[index]
    assert detection["analyzer_coverage"]["unavailable_reason"] == "legacy_receipt"  # type: ignore[index]


async def test_unknown_operation_delegates_unchanged() -> None:
    fallback = RecordingFallback()
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        fallback,
    )

    result = await reader.read(_query("ontology.graph"))

    assert result == {"operation": "ontology.graph"}
    assert fallback.operations == ["ontology.graph"]


async def test_assurance_twin_review_detail_round_trips_an_opaque_slashed_key(
    monkeypatch: Any,
) -> None:
    """The review key is opaque identity: a `/` survives, unchanged, to the row key."""

    body = {
        "pr_ref": "owner/repo#12",
        "review_key": "Owner/Repo#12:Change_A",
        "verdict": "needs_review",
        "mode": "shadow",
        "generated_at": "2026-07-07T00:00:00Z",
        "freshness": "fresh",
        "reason_codes": [],
        "metadata": {},
        "findings": [],
    }
    material = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    value = {
        **body,
        "activity_id": "assurance-twin.change-review:Owner/Repo#12:Change_A:completed",
        "correlation_id": "correlation-1",
        "evidence_digest": f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}",
        "evidence_source_revision": f"sha256:{'1' * 64}",
    }
    statements: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self
        statements.append((statement, parameters))
        return [{"value": value}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    detail = await reader.read(
        _query(
            "assurance_twin.review_detail",
            params={"review_key": ("Owner/Repo#12:Change_A",)},
        )
    )

    assert statements[0][1] == ("runtime:assurance-twin-review:Owner/Repo#12:Change_A",)
    assert detail["available"] is True
    review = detail["review"]
    assert isinstance(review, dict)
    assert review["review_key"] == "Owner/Repo#12:Change_A"


async def test_assurance_twin_review_list_rejects_a_mismatched_durable_key(
    monkeypatch: Any,
) -> None:
    body = {
        "pr_ref": "owner/repo#12",
        "review_key": "claimed-key",
        "verdict": "needs_review",
        "mode": "shadow",
        "generated_at": "2026-07-07T00:00:00Z",
        "freshness": "fresh",
        "reason_codes": [],
        "metadata": {},
        "findings": [],
    }
    material = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    value = {
        **body,
        "activity_id": "assurance-twin.change-review:identity:completed",
        "correlation_id": "correlation-1",
        "evidence_digest": f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}",
        "evidence_source_revision": f"sha256:{'1' * 64}",
    }
    statements: list[str] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        return [{"key": "runtime:assurance-twin-review:durable-key", "value": value}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    result = await reader.read(_query("assurance_twin.reviews"))

    assert "SELECT key, value" in statements[0]
    assert result["available"] is False
    assert result["reviews"] == []
    gaps = result["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["identity"] is None
    assert gaps[0]["reason_code"] == GAP_MALFORMED


async def test_assurance_twin_posture_rejects_a_mismatched_durable_key(
    monkeypatch: Any,
) -> None:
    body = {
        "scope": "claimed-scope",
        "generated_at": "2026-07-07T00:00:00Z",
        "mode": "shadow",
        "verdict": "clear",
        "blocks_action": False,
        "resource_count": 1,
        "rule_count": 1,
        "highest_severity": None,
        "severity_counts": {"low": 0, "medium": 0, "high": 0, "critical": 0},
        "findings": [],
        "freshness": "fresh",
        "reason_codes": [],
    }
    material = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    value = {
        **body,
        "activity_id": "assurance-twin.posture-report:identity:completed",
        "correlation_id": "correlation-1",
        "evidence_digest": f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}",
        "evidence_source_revision": f"sha256:{'1' * 64}",
    }
    statements: list[str] = []

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        return [{"key": "runtime:assurance-twin-posture:durable-scope", "value": value}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    result = await reader.read(_query("assurance_twin.posture"))

    assert "SELECT key, value" in statements[0]
    assert result["available"] is False
    assert result["reports"] == []
    gaps = result["gaps"]
    assert isinstance(gaps, list)
    assert gaps[0]["identity"] is None
    assert gaps[0]["reason_code"] == GAP_MALFORMED


async def test_assurance_twin_review_detail_requires_a_bounded_key() -> None:
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    with pytest.raises(ProjectionNotFoundError):
        await reader.read(_query("assurance_twin.review_detail"))
    with pytest.raises(ProjectionNotFoundError):
        await reader.read(
            _query("assurance_twin.review_detail", params={"review_key": ("x" * 257,)})
        )


async def test_assurance_twin_review_detail_rejects_a_mismatched_stored_key(
    monkeypatch: Any,
) -> None:
    """A row fetched by one key whose body claims a different key is unavailable.

    Guards against ever rendering another identity's finding evidence under
    the requested key - the row's own ``review_key`` field MUST bind byte
    for byte to the exact key just queried, with no case-folding or other
    normalisation on either side.
    """

    body = {
        "pr_ref": "owner/repo#12",
        "review_key": "Owner/Repo#12:Change_A",
        "verdict": "needs_review",
        "mode": "shadow",
        "generated_at": "2026-07-07T00:00:00Z",
        "freshness": "fresh",
        "reason_codes": [],
        "metadata": {},
        "findings": [],
    }
    material = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    value = {
        **body,
        "activity_id": "assurance-twin.change-review:Owner/Repo#12:Change_A:completed",
        "correlation_id": "correlation-1",
        "evidence_digest": f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}",
        "evidence_source_revision": f"sha256:{'1' * 64}",
    }

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [{"value": value}]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    # A case-folded variant of the stored key is a different key entirely.
    detail = await reader.read(
        _query(
            "assurance_twin.review_detail",
            params={"review_key": ("owner/repo#12:change_a",)},
        )
    )

    assert detail["available"] is False
    assert detail["review"] is None
    gap = detail["gap"]
    assert isinstance(gap, dict)
    assert gap["reason_code"] == GAP_MALFORMED
    # No fragment of the other identity's finding evidence is exposed.
    assert gap["identity"] is None
