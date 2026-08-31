"""Focused tests for durable Process and automation blueprint projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.families.operations import (
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
        if "FROM process_event" in statement:
            return [event]
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
    assert calls[0][1] == ("architecture-review",)


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
        return events if "FROM process_event" in statement else [process]

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
        if "FROM process_event" in statement:
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


async def test_empty_autonomy_window_remains_an_authoritative_measurement(
    monkeypatch: Any,
) -> None:
    observed_at = datetime(2026, 8, 27, tzinfo=UTC)

    async def fetch(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self
        return [{"observed_at": observed_at}] if "MAX(created_at)" in statement else []

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        RecordingFallback(),
    )

    result = await reader.read(_query("autonomy"))

    assert result["synthetic"] is False
    assert result["sample_size"] == 0
    assert result["source"] == {
        "name": "postgresql:audit_log",
        "kind": "audit",
        "as_of": observed_at.isoformat(),
    }
    assert result["success"]["auto_resolution_rate"]["value"] is None
    assert result["attribution"]["coverage"] is None
    assert result["verticals"] == []


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
                }
            ]
        if "GROUP BY COALESCE(closure_reason" in statement:
            return []
        if "FROM forecast_publication_outbox" in statement:
            return [{"pending": 0, "dead_lettered": 0, "oldest_pending_at": None}]
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
    assert delivery["retry_count"] == 1
    assert delivery["acknowledgement_count"] == 1
    assert forecast["episodes"]["total"] == 0
    assert forecast["episodes"]["closure_completeness"] is None
    assert memory["items"][0]["id"] == "memory-1"
    assert memory["items"][0]["active"] is True
    assert skills["installed_count"] == 0
    assert skills["diagnostics"][0]["status"] == "ready"
    assert detection["target_count"] == 0
    assert detection["counts"]["unknown"] == 0
    assert detection["lifecycle"]["status"] == "available"
    assert detection["lifecycle"]["target_count"] == 0
    assert detection["lifecycle"]["cause_claim_supported"] is False
    assert detection["lifecycle"]["execution_authority"] is False
    assert baselines["baseline"]["version"] == "not-published"
    assert baselines["drift"]["verdict"] == "not-evaluated"


async def test_unknown_operation_delegates_unchanged() -> None:
    fallback = RecordingFallback()
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        fallback,
    )

    result = await reader.read(_query("ontology.graph"))

    assert result == {"operation": "ontology.graph"}
    assert fallback.operations == ["ontology.graph"]
