"""Focused tests for owner-scoped Operator task-worker projection materialization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fdai_operator_service.families.conversation.contracts import (
    ConversationQuery,
    PrincipalScope,
)
from fdai_operator_service.task_worker_projection import (
    SqlTaskWorkerProjectionStore,
    TaskWorkerProjectionMaterializer,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


class _RecordingSqlBackend:
    """Fake SQL backend verifying cancellation_owner predicate binding inside each query."""

    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []
        self.run_rows: dict[str, dict[str, Any]] = {
            "worker-owned-a": {
                "worker_id": "worker-owned-a",
                "parent_trace_ref": "trace-a",
                "cancellation_owner": "principal-a",
                "status": "succeeded",
                "request": {
                    "worker_id": "worker-owned-a",
                    "parent_trace_ref": "trace-a",
                    "cancellation_owner": "principal-a",
                    "goal": "Sensitive investigation goal for principal A",
                    "constraints": ["no-cross-tenant"],
                    "evidence_refs": ["inv:vm-1", "inv:vm-2"],
                    "budget": {
                        "max_wall_seconds": 30.0,
                        "max_tool_calls": 8,
                        "max_tokens": 4096,
                        "max_cost_microusd": 500000,
                        "heartbeat_seconds": 5.0,
                    },
                },
                "capabilities": {
                    "allowed_tools": ["get_resource_state", "resolve_resource"],
                    "denied_tools": [],
                },
                "usage": {"tokens": 250, "cost_microusd": 900, "tool_calls": 2},
                "result": {
                    "worker_id": "worker-owned-a",
                    "parent_trace_ref": "trace-a",
                    "status": "succeeded",
                    "summary": "VM state is running.",
                    "evidence_refs": ["inv:vm-1"],
                    "caveats": [],
                    "usage": {"tokens": 250, "cost_microusd": 900, "tool_calls": 2},
                    "terminal_reason": "completed",
                    "started_at": "2026-11-01T12:00:01+00:00",
                    "finished_at": "2026-11-01T12:00:04+00:00",
                    "trusted": False,
                },
                "created_at": NOW,
                "updated_at": NOW,
                "heartbeat_at": NOW,
            },
            "worker-owned-b": {
                "worker_id": "worker-owned-b",
                "parent_trace_ref": "trace-b",
                "cancellation_owner": "principal-b",
                "status": "running",
                "request": {
                    "worker_id": "worker-owned-b",
                    "parent_trace_ref": "trace-b",
                    "cancellation_owner": "principal-b",
                    "goal": "Principal B goal",
                    "constraints": [],
                    "evidence_refs": ["inv:aks-1"],
                    "budget": {
                        "max_wall_seconds": 30.0,
                        "max_tool_calls": 8,
                        "max_tokens": 4096,
                        "max_cost_microusd": 500000,
                        "heartbeat_seconds": 5.0,
                    },
                },
                "capabilities": {"allowed_tools": ["resolve_resource"], "denied_tools": []},
                "usage": {"tokens": 0, "cost_microusd": 0, "tool_calls": 0},
                "result": None,
                "created_at": NOW,
                "updated_at": NOW,
                "heartbeat_at": None,
            },
        }
        self.event_rows: dict[str, list[dict[str, Any]]] = {
            "worker-owned-a": [
                {
                    "worker_id": "worker-owned-a",
                    "sequence": 0,
                    "kind": "worker.created",
                    "at": NOW,
                    "details": [["parent_trace_ref", "trace-a"]],
                },
                {
                    "worker_id": "worker-owned-a",
                    "sequence": 1,
                    "kind": "worker.succeeded",
                    "at": NOW,
                    "details": [["reason", "completed"]],
                },
            ],
            "worker-owned-b": [
                {
                    "worker_id": "worker-owned-b",
                    "sequence": 0,
                    "kind": "worker.created",
                    "at": NOW,
                    "details": [["parent_trace_ref", "trace-b"]],
                }
            ],
        }

    async def __call__(self, sql: str, params: tuple[object, ...]) -> Sequence[Mapping[str, Any]]:
        self.queries.append((sql, params))
        assert "cancellation_owner = %s" in sql
        if "FROM task_worker_run WHERE cancellation_owner = %s" in sql:
            owner = str(params[0])
            return [row for row in self.run_rows.values() if row["cancellation_owner"] == owner]
        if "FROM task_worker_run WHERE worker_id = %s AND cancellation_owner = %s" in sql:
            worker_id, owner = str(params[0]), str(params[1])
            row = self.run_rows.get(worker_id)
            if row is None or row["cancellation_owner"] != owner:
                return []
            return [row]
        if "FROM task_worker_event" in sql:
            worker_id, owner = str(params[0]), str(params[1])
            row = self.run_rows.get(worker_id)
            if row is None or row["cancellation_owner"] != owner:
                return []
            return list(reversed(self.event_rows.get(worker_id, [])))
        raise AssertionError(f"unexpected SQL: {sql}")


async def test_workers_list_get_and_events_enforce_owner_predicates_and_404_equivalence() -> None:
    backend = _RecordingSqlBackend()
    store = SqlTaskWorkerProjectionStore(fetch_all=backend)
    materializer = TaskWorkerProjectionMaterializer(store=store)
    scope_a = PrincipalScope(subject_id="principal-a", roles=frozenset({"Reader"}))

    list_resp = await materializer.read(ConversationQuery(operation="workers.list", scope=scope_a))
    assert list_resp.status_code == 200
    assert isinstance(list_resp.body, dict)
    assert list_resp.body["read_only"] is True
    assert list_resp.body["execution_authority"] == "none"
    workers = list_resp.body["workers"]
    assert isinstance(workers, list) and len(workers) == 1
    row = workers[0]
    assert isinstance(row, dict)
    assert row["worker_id"] == "worker-owned-a"
    assert "goal" not in row
    assert "constraints" not in row
    assert row["evidence_count"] == 2
    assert row["summary_truncated"] is False
    assert row["trusted"] is False

    detail_resp = await materializer.read(
        ConversationQuery(
            operation="workers.get",
            scope=scope_a,
            path_params={"worker_id": "worker-owned-a"},
        )
    )
    assert detail_resp.status_code == 200
    assert isinstance(detail_resp.body, dict)
    worker_detail = detail_resp.body["worker"]
    assert isinstance(worker_detail, dict)
    assert worker_detail["result"]["summary"] == "VM state is running."
    assert worker_detail["result"]["trusted"] is False

    events_resp = await materializer.read(
        ConversationQuery(
            operation="workers.events",
            scope=scope_a,
            path_params={"worker_id": "worker-owned-a"},
        )
    )
    assert events_resp.status_code == 200
    assert isinstance(events_resp.body, dict)
    events = events_resp.body["events"]
    assert isinstance(events, list) and [e["kind"] for e in events] == [
        "worker.created",
        "worker.succeeded",
    ]

    foreign_get = await materializer.read(
        ConversationQuery(
            operation="workers.get",
            scope=scope_a,
            path_params={"worker_id": "worker-owned-b"},
        )
    )
    missing_get = await materializer.read(
        ConversationQuery(
            operation="workers.get",
            scope=scope_a,
            path_params={"worker_id": "worker-does-not-exist"},
        )
    )
    assert foreign_get.status_code == 404
    assert missing_get.status_code == 404
    assert isinstance(foreign_get.body, dict) and isinstance(missing_get.body, dict)
    assert foreign_get.body["error"]["code"] == missing_get.body["error"]["code"]
    assert foreign_get.body["error"]["message"] == missing_get.body["error"]["message"]

    foreign_events = await materializer.read(
        ConversationQuery(
            operation="workers.events",
            scope=scope_a,
            path_params={"worker_id": "worker-owned-b"},
        )
    )
    missing_events = await materializer.read(
        ConversationQuery(
            operation="workers.events",
            scope=scope_a,
            path_params={"worker_id": "worker-does-not-exist"},
        )
    )
    assert foreign_events.status_code == 404
    assert missing_events.status_code == 404
    assert isinstance(foreign_events.body, dict) and isinstance(missing_events.body, dict)
    assert foreign_events.body["error"]["code"] == missing_events.body["error"]["code"]
    assert all("cancellation_owner = %s" in sql for sql, _ in backend.queries)


async def test_worker_projection_rejects_path_separators_control_chars_and_bool_limit() -> None:
    import pytest
    from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError

    backend = _RecordingSqlBackend()
    store = SqlTaskWorkerProjectionStore(fetch_all=backend)
    materializer = TaskWorkerProjectionMaterializer(store=store)
    scope_a = PrincipalScope(subject_id="principal-a", roles=frozenset({"Reader"}))

    for bad_id in ("../worker-1", "worker/1", "worker\\1", "worker-\x001", "worker-\n1"):
        with pytest.raises(ConversationBoundaryError) as id_exc:
            await materializer.read(
                ConversationQuery(
                    operation="workers.get",
                    scope=scope_a,
                    path_params={"worker_id": bad_id},
                )
            )
        assert id_exc.value.status_code == 400
        assert id_exc.value.code == "invalid_worker_id"

    for bad_limit in (True, False):
        with pytest.raises(ConversationBoundaryError) as limit_exc:
            await materializer.read(
                ConversationQuery(
                    operation="workers.list",
                    scope=scope_a,
                    query={"limit": bad_limit},
                )
            )
        assert limit_exc.value.status_code == 400
        assert limit_exc.value.code == "invalid_limit"
