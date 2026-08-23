"""Atomic completion audit marker tests for durable background tasks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.background_task.completion_sink import (
    BackgroundTaskTurn,
    ConversationCompletionSink,
)
from fdai.core.background_task.models import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)
from fdai.delivery.persistence.background_task_completion_audit import (
    BackgroundTaskCompletionAuditConflictError,
    StateStoreBackgroundTaskCompletionAudit,
)
from fdai.shared.providers.conversation_delivery import InMemoryConversationDeliveryStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 8, 23, 4, 0, tzinfo=UTC)


def _attempt() -> BackgroundTaskAttempt:
    task = BackgroundTask(
        task_id="task-1",
        owner_principal_id="principal-1",
        origin=BackgroundTaskOrigin(
            conversation_id="conversation-1",
            channel_kind="web",
            channel_id="channel-1",
        ),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded resource evidence",
        context_digest="context-1",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-1",
        idempotency_key="request-1",
        created_at=NOW - timedelta(minutes=1),
        retention_until=NOW + timedelta(days=30),
    )
    result = BackgroundTaskResult(
        summary="The bounded investigation completed.",
        evidence_refs=("evidence-1",),
        terminal_reason="completed",
        usage=BackgroundTaskUsage(tokens=10, cost_microusd=20, tool_calls=2),
        started_at=NOW - timedelta(seconds=5),
        finished_at=NOW,
    )
    return BackgroundTaskAttempt(
        attempt_id="task-1:1",
        task=task,
        attempt_number=1,
        status=BackgroundTaskStatus.SUCCEEDED,
        revision=3,
        updated_at=NOW,
        usage=result.usage,
        result=result,
    )


async def test_completion_audit_markers_and_entries_are_single_write() -> None:
    store = InMemoryStateStore()
    writer = StateStoreBackgroundTaskCompletionAudit(store=store, clock=lambda: NOW)
    attempt = _attempt()

    await writer.record_completed(attempt)
    await writer.record_completed(attempt)
    await writer.record_delivery_enqueued(attempt)
    await writer.record_delivery_enqueued(attempt)

    entries = tuple(store.audit_entries)
    assert [entry["entry"]["action_kind"] for entry in entries] == [
        "background-task.completed",
        "background-task.delivery-enqueued",
    ]
    assert {entry["entry"]["mode"] for entry in entries} == {"shadow"}
    assert await store.verify_chain() is True


async def test_concurrent_marker_replay_writes_one_audit_entry() -> None:
    store = InMemoryStateStore()
    writer = StateStoreBackgroundTaskCompletionAudit(store=store, clock=lambda: NOW)
    attempt = _attempt()

    await asyncio.gather(*(writer.record_completed(attempt) for _ in range(10)))

    entries = tuple(store.audit_entries)
    assert len(entries) == 1
    assert entries[0]["entry"]["attempt_id"] == attempt.attempt_id


async def test_marker_payload_conflict_fails_closed() -> None:
    store = InMemoryStateStore()
    writer = StateStoreBackgroundTaskCompletionAudit(store=store, clock=lambda: NOW)
    attempt = _attempt()
    await writer.record_completed(attempt)
    assert attempt.result is not None
    conflicting = replace(
        attempt,
        result=replace(attempt.result, terminal_reason="different-result"),
    )

    with pytest.raises(BackgroundTaskCompletionAuditConflictError, match="payload conflict"):
        await writer.record_completed(conflicting)

    assert len(tuple(store.audit_entries)) == 1


async def test_completion_audit_requires_terminal_result_and_aware_clock() -> None:
    store = InMemoryStateStore()
    attempt = _attempt()
    queued = replace(
        attempt,
        status=BackgroundTaskStatus.QUEUED,
        lease=None,
        result=None,
    )
    writer = StateStoreBackgroundTaskCompletionAudit(store=store, clock=lambda: NOW)
    with pytest.raises(ValueError, match="terminal"):
        await writer.record_completed(queued)

    naive = StateStoreBackgroundTaskCompletionAudit(
        store=store,
        clock=lambda: datetime(2026, 8, 23, 4, 0),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        await naive.record_completed(attempt)

    assert not tuple(store.audit_entries)


async def test_concurrent_completion_publish_is_single_write_end_to_end() -> None:
    class _Appender:
        def __init__(self) -> None:
            self.turns: dict[str, BackgroundTaskTurn] = {}

        async def append(self, turn: BackgroundTaskTurn) -> None:
            existing = self.turns.get(turn.turn_id)
            if existing is not None and existing != turn:
                raise AssertionError("completion replay attempted to rewrite a turn")
            self.turns[turn.turn_id] = turn

    state_store = InMemoryStateStore()
    delivery_store = InMemoryConversationDeliveryStore()
    appender = _Appender()
    sink = ConversationCompletionSink(
        appender=appender,
        deliveries=delivery_store,
        audit=StateStoreBackgroundTaskCompletionAudit(
            store=state_store,
            clock=lambda: NOW,
        ),
        scope_ref="scope-1",
        clock=lambda: NOW,
    )
    attempt = _attempt()

    await asyncio.gather(*(sink.publish(attempt) for _ in range(10)))

    assert len(appender.turns) == 1
    assert len((await delivery_store.snapshot()).deliveries) == 1
    assert [entry["entry"]["action_kind"] for entry in state_store.audit_entries] == [
        "background-task.completed",
        "background-task.delivery-enqueued",
    ]
