"""Owner-scoped background-task projection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai_operator_service.families.conversation.background_tasks import (
    BackgroundTaskProgressProjection,
    BackgroundTaskProjection,
    materialize_background_task,
    open_background_task_stream,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationStreamRequest,
    PrincipalScope,
)
from fdai_operator_service.family_adapters import PostgresConversationAdapters
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    _background_task_projection,
)

NOW = datetime(2026, 8, 23, 5, 0, tzinfo=UTC)


def _task(task_id: str, *, owner: str = "principal-a", terminal: bool = False):
    del owner
    return BackgroundTaskProjection(
        task_id=task_id,
        attempt_id=f"{task_id}:1",
        kind="read_only_investigation",
        status="succeeded" if terminal else "running",
        revision=3,
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW,
        retention_until=NOW + timedelta(days=30),
        budget={"max_wall_seconds": 300},
        usage={"tokens": 10, "cost_microusd": 20, "tool_calls": 1},
        request_summary="Investigate the latency regression after the rollout.",
        accountable_agent="Heimdall",
        result_summary="The rollout correlates with elevated dependency latency."
        if terminal
        else None,
        evidence_refs=("metric:dependency-latency",) if terminal else (),
        terminal_reason="completed" if terminal else None,
        started_at=NOW - timedelta(seconds=5),
        finished_at=NOW if terminal else None,
        completion_state="pending" if terminal else None,
    )


class _Store:
    def __init__(self) -> None:
        self.tasks = {
            ("principal-a", "task-a"): _task("task-a"),
            ("principal-a", "task-done"): _task("task-done", terminal=True),
            ("principal-b", "task-private"): _task("task-private"),
        }

    async def list_background_tasks(self, **kwargs: object):
        owner = str(kwargs["owner_principal_id"])
        limit = int(kwargs["limit"])
        return tuple(task for (principal, _), task in self.tasks.items() if principal == owner)[
            :limit
        ]

    async def read_background_task(self, **kwargs: object):
        return self.tasks.get((str(kwargs["owner_principal_id"]), str(kwargs["task_id"])))

    async def read_background_task_progress(self, **kwargs: object):
        after = int(kwargs["after_sequence"])
        events = (
            BackgroundTaskProgressProjection(
                sequence=0,
                kind="investigation.started",
                message="Investigation started.",
                at=NOW - timedelta(seconds=4),
                usage={"tokens": 0, "cost_microusd": 0, "tool_calls": 0},
            ),
            BackgroundTaskProgressProjection(
                sequence=1,
                kind="investigation.completed",
                message="Investigation completed.",
                at=NOW,
                usage={"tokens": 10, "cost_microusd": 20, "tool_calls": 1},
            ),
        )
        return tuple(event for event in events if event.sequence > after)


def _query(operation: str, *, task_id: str | None = None, query=None):
    path_params = {} if task_id is None else {"task_id": task_id}
    return ConversationQuery(
        operation=operation,
        scope=PrincipalScope(subject_id="principal-a"),
        query=query or {},
        path_params=path_params,
    )


async def test_list_and_detail_expose_only_bounded_projection() -> None:
    store = _Store()

    listed = await materialize_background_task(_query("background.list"), store=store)
    detail = await materialize_background_task(
        _query("background.get", task_id="task-done"), store=store
    )

    assert listed is not None and listed.body is not None
    assert len(listed.body["tasks"]) == 2
    assert detail is not None and detail.body is not None
    task = detail.body["task"]
    assert task["duration_seconds"] == 5.0
    assert task["request_summary"] == "Investigate the latency regression after the rollout."
    assert task["accountable_agent"] == "Heimdall"
    assert task["execution_worker"] == "background-task-coordinator"
    assert task["result_summary"] == ("The rollout correlates with elevated dependency latency.")
    assert task["evidence_refs"] == ["metric:dependency-latency"]
    assert "prompt" not in task and "context_digest" not in task


async def test_legacy_task_keeps_agent_attribution_unknown() -> None:
    task = _task("task-legacy")
    legacy = BackgroundTaskProjection(
        **{
            field: getattr(task, field)
            for field in task.__dataclass_fields__
            if field not in {"request_summary", "accountable_agent"}
        }
    )
    store = _Store()
    store.tasks[("principal-a", "task-legacy")] = legacy

    detail = await materialize_background_task(
        _query("background.get", task_id="task-legacy"), store=store
    )

    assert detail is not None and detail.body is not None
    projected = detail.body["task"]
    assert projected["request_summary"] is None
    assert projected["accountable_agent"] is None


def test_postgres_projection_retains_bounds_and_rejects_wrong_attribution() -> None:
    row: dict[str, object] = {
        "task_id": "task-one",
        "attempt_id": "attempt-one",
        "task_kind": "read_only_investigation",
        "status": "succeeded",
        "revision": 3,
        "created_at": NOW,
        "updated_at": NOW,
        "retention_until": NOW + timedelta(days=30),
        "lease_expires_at": None,
        "budget": {"max_wall_seconds": 300},
        "usage": {"tokens": 0, "cost_microusd": 0, "tool_calls": 1},
        "terminal_reason": "completed",
        "started_at": NOW,
        "finished_at": NOW,
        "completion_state": "pending",
        "request_summary": "Inspect one resource",
        "request_truncated": False,
        "accountable_agent": "Heimdall",
        "result_summary": "One bounded result",
        "result_truncated": False,
        "evidence_refs": ["azure:resource-one"],
        "evidence_truncated": False,
    }

    projection = _background_task_projection(row)

    assert projection.request_summary == "Inspect one resource"
    assert projection.result_summary == "One bounded result"
    assert projection.evidence_refs == ("azure:resource-one",)
    with pytest.raises(PostgresFamilyStoreUnavailable, match="accountable_agent"):
        _background_task_projection({**row, "accountable_agent": "Thor"})


async def test_cross_owner_task_is_indistinguishable_from_missing() -> None:
    store = _Store()

    with pytest.raises(ConversationBoundaryError) as private_error:
        await materialize_background_task(
            _query("background.get", task_id="task-private"), store=store
        )
    with pytest.raises(ConversationBoundaryError) as missing_error:
        await materialize_background_task(
            _query("background.get", task_id="task-missing"), store=store
        )

    assert (private_error.value.status_code, private_error.value.code) == (404, "not_found")
    assert (missing_error.value.status_code, missing_error.value.code) == (404, "not_found")


async def test_progress_cursor_and_terminal_stream_are_monotonic() -> None:
    store = _Store()
    progress = await materialize_background_task(
        _query("background.progress", task_id="task-done", query={"after": "0"}),
        store=store,
    )
    stream = await open_background_task_stream(
        ConversationStreamRequest(
            operation="background.progress_stream",
            scope=PrincipalScope(subject_id="principal-a"),
            path_params={"task_id": "task-done"},
            after_event_id="0",
        ),
        store=store,
    )

    assert progress is not None and progress.body is not None
    assert [item["sequence"] for item in progress.body["events"]] == [1]
    assert progress.body["has_more"] is False
    assert stream is not None
    events = [event async for event in stream]
    assert [event.event for event in events] == ["progress", "terminal"]
    assert [event.event_id for event in events] == ["1", "task-done:1:terminal"]

    replay = await open_background_task_stream(
        ConversationStreamRequest(
            operation="background.progress_stream",
            scope=PrincipalScope(subject_id="principal-a"),
            path_params={"task_id": "task-done"},
            after_event_id="task-done:1:terminal",
        ),
        store=store,
    )
    assert replay is not None
    assert [event async for event in replay] == []


async def test_terminal_stream_pages_all_progress_before_terminal() -> None:
    class _LargeProgressStore(_Store):
        async def read_background_task_progress(self, **kwargs: object):
            after = int(kwargs["after_sequence"])
            limit = int(kwargs["limit"])
            return tuple(
                BackgroundTaskProgressProjection(
                    sequence=sequence,
                    kind="investigation.progress",
                    message=f"Progress {sequence}",
                    at=NOW,
                    usage={"tokens": sequence, "cost_microusd": 0, "tool_calls": 0},
                )
                for sequence in range(after + 1, min(150, after + 1 + limit))
            )

    store = _LargeProgressStore()
    first = await open_background_task_stream(
        ConversationStreamRequest(
            operation="background.progress_stream",
            scope=PrincipalScope(subject_id="principal-a"),
            path_params={"task_id": "task-done"},
        ),
        store=store,
    )
    assert first is not None
    first_events = [event async for event in first]
    assert len(first_events) == 100
    assert first_events[-1].event_id == "99"
    assert all(event.event == "progress" for event in first_events)

    second = await open_background_task_stream(
        ConversationStreamRequest(
            operation="background.progress_stream",
            scope=PrincipalScope(subject_id="principal-a"),
            path_params={"task_id": "task-done"},
            after_event_id="99",
        ),
        store=store,
    )
    assert second is not None
    second_events = [event async for event in second]
    assert [event.event_id for event in second_events] == [
        *(str(sequence) for sequence in range(100, 150)),
        "task-done:1:terminal",
    ]


async def test_running_stream_emits_bounded_heartbeat_when_idle() -> None:
    store = _Store()
    stream = await open_background_task_stream(
        ConversationStreamRequest(
            operation="background.progress_stream",
            scope=PrincipalScope(subject_id="principal-a"),
            path_params={"task_id": "task-a"},
            after_event_id="1",
        ),
        store=store,
    )

    assert stream is not None
    events = [event async for event in stream]
    assert len(events) == 1
    assert events[0].event == "heartbeat"
    assert events[0].retry_ms == 1_000


async def test_invalid_cursor_fails_before_store_read() -> None:
    with pytest.raises(ConversationBoundaryError, match="cursor MUST be complete"):
        await materialize_background_task(
            _query("background.list", query={"before_task_id": "task-a"}),
            store=_Store(),
        )


async def test_postgres_conversation_adapter_uses_task_materializers() -> None:
    adapter = PostgresConversationAdapters(cast(PostgresFamilyStore, _Store()))

    detail = await adapter.read(_query("background.get", task_id="task-done"))
    stream = await adapter.open(
        ConversationStreamRequest(
            operation="background.progress_stream",
            scope=PrincipalScope(subject_id="principal-a"),
            path_params={"task_id": "task-done"},
            after_event_id="0",
        )
    )

    assert detail.body is not None and detail.body["task"]["task_id"] == "task-done"
    assert [event.event async for event in stream] == ["progress", "terminal"]
