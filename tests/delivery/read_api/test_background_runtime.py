from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)
from fdai.delivery.read_api.background_runtime import (
    ConversationBackgroundTaskCompletionSink,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.providers.user_context import ConversationRecord


async def test_completion_sink_appends_one_provenance_labeled_turn() -> None:
    history = InMemoryConversationHistoryStore()
    now = datetime(2026, 7, 20, tzinfo=UTC)
    await history.create_conversation(
        ConversationRecord(
            conversation_id="conversation-one",
            principal_id="operator-one",
            channel_id="channel-one",
            started_at=now,
            last_active=now,
        )
    )
    task = BackgroundTask(
        task_id="background-one",
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence.",
        context_digest="sha256:context",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        created_at=now,
        retention_until=now + timedelta(days=30),
    )
    result = BackgroundTaskResult(
        summary="Completed.",
        evidence_refs=(),
        terminal_reason="completed",
        usage=BackgroundTaskUsage(),
        started_at=now,
        finished_at=now,
    )
    attempt = BackgroundTaskAttempt(
        attempt_id="background-one:1",
        task=task,
        attempt_number=1,
        status=BackgroundTaskStatus.SUCCEEDED,
        revision=4,
        updated_at=now,
        result=result,
    )
    audit = InMemoryStateStore()
    sink = ConversationBackgroundTaskCompletionSink(history=history, audit=audit)

    await sink.publish(attempt)
    await sink.publish(attempt)
    turns = await history.list_turns(
        principal_id="operator-one",
        conversation_id="conversation-one",
    )

    assert len(turns) == 1
    assert turns[0].content == "[Background task result: background-one]\nCompleted."
    assert turns[0].metadata["trusted"] == "false"
    assert turns[0].idempotency_key == "background-completion:background-one:1"
    audit_entries = tuple(audit.audit_entries)
    assert len(audit_entries) == 2
    assert audit_entries[0]["entry"]["action_kind"] == "background-task.completed"
