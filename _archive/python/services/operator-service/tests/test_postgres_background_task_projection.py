"""PostgreSQL query boundary tests for background-task projections."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
)

NOW = datetime(2026, 8, 23, 5, 0, tzinfo=UTC)


def _task_row() -> dict[str, object]:
    return {
        "task_id": "task-one",
        "attempt_id": "task-one:1",
        "task_kind": "read_only_investigation",
        "status": "running",
        "revision": 2,
        "created_at": NOW,
        "updated_at": NOW,
        "retention_until": NOW,
        "lease_expires_at": NOW,
        "budget": {"max_wall_seconds": 300},
        "usage": {"tokens": 1, "cost_microusd": 2, "tool_calls": 1},
        "progress_watermark": None,
        "latest_progress_order": 0,
        "terminal_reason": None,
        "started_at": None,
        "finished_at": None,
        "completion_state": None,
        "request_summary": "Inspect the resource",
        "request_truncated": False,
        "accountable_agent": "Heimdall",
        "result_summary": None,
        "result_truncated": False,
        "evidence_refs": [],
        "evidence_truncated": False,
    }


async def test_postgres_task_reads_bind_owner_in_every_query(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fetch_all(
        _store: PostgresFamilyStore,
        query: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        calls.append((query, params))
        if "SELECT progress.progress_sequence AS sequence" in query:
            return [
                {
                    "sequence": 0,
                    "progress_order": 1,
                    "kind": "investigation.started",
                    "message": "Investigation started.",
                    "at": NOW,
                    "usage": {"tokens": 0, "cost_microusd": 0, "tool_calls": 0},
                }
            ]
        return [_task_row()]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    listed = await store.list_background_tasks(
        owner_principal_id="principal-a",
        before_updated_at=None,
        before_task_id=None,
        limit=2,
    )
    detail = await store.read_background_task(
        owner_principal_id="principal-a",
        task_id="task-one",
    )
    progress = await store.read_background_task_progress(
        owner_principal_id="principal-a",
        task_id="task-one",
        after_sequence=-1,
        limit=100,
    )

    assert listed[0].task_id == "task-one"
    assert detail is not None and detail.task_id == "task-one"
    assert progress[0].sequence == 0
    assert all(params["owner_principal_id"] == "principal-a" for _, params in calls)
    assert "FROM operator_background_task_projection AS task" in calls[0][0]
    assert "FROM operator_background_task_projection AS task" in calls[1][0]
    assert "FROM operator_background_task_progress AS progress" in calls[2][0]
    assert "task.progress_watermark" in calls[0][0]
    assert "MAX(progress.progress_order)" in calls[1][0]
    assert "progress.progress_order AS progress_order" in calls[2][0]
    assert "task.principal_id = %(owner_principal_id)s" in calls[0][0]
    assert "task.principal_id = %(owner_principal_id)s" in calls[1][0]
    assert "progress.principal_id = %(owner_principal_id)s" in calls[2][0]
    select_clause = calls[0][0].split("FROM", maxsplit=1)[0]
    assert "background_task_attempt" not in calls[0][0]
    assert "background_task_progress" not in calls[2][0].replace(
        "operator_background_task_progress", ""
    )
    assert "task.task_kind" in select_clause


async def test_postgres_task_reads_live_filter_expired_rows_when_purge_lags(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fetch_all(
        _store: PostgresFamilyStore,
        query: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        calls.append((query, params))
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert (
        await store.list_background_tasks(
            owner_principal_id="principal-a",
            before_updated_at=None,
            before_task_id=None,
            limit=2,
        )
        == ()
    )
    assert (
        await store.read_background_task(
            owner_principal_id="principal-a",
            task_id="task-one",
        )
        is None
    )
    assert (
        await store.read_background_task_progress(
            owner_principal_id="principal-a",
            task_id="task-one",
            after_sequence=-1,
            limit=100,
        )
        == ()
    )

    assert "task.retention_until > CURRENT_TIMESTAMP" in calls[0][0]
    assert "task.retention_until > CURRENT_TIMESTAMP" in calls[1][0]
    assert "progress.retention_until > CURRENT_TIMESTAMP" in calls[1][0]
    assert "progress.retention_until > CURRENT_TIMESTAMP" in calls[2][0]


async def test_postgres_task_reads_accept_the_contract_identifier_ceiling(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        _store: PostgresFamilyStore,
        _query: str,
        _params: dict[str, object],
    ) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    identifier = "a" * 256

    assert (
        await store.read_background_task(
            owner_principal_id=identifier,
            task_id=identifier,
        )
        is None
    )


async def test_postgres_task_projection_rejects_unknown_stored_states(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        _store: PostgresFamilyStore,
        _query: str,
        _params: dict[str, object],
    ) -> list[dict[str, object]]:
        return [{**_task_row(), "status": "invented"}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresFamilyStoreUnavailable, match="status is malformed"):
        await store.read_background_task(
            owner_principal_id="principal-a",
            task_id="task-one",
        )
