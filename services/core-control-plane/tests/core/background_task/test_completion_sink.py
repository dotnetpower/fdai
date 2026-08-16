"""The background completion sink replays without rerunning the investigation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.background_task.completion_sink import (
    BackgroundTaskTurn,
    CompletionSinkError,
    ConversationCompletionSink,
    build_turn,
    completion_origin_ref,
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
from fdai.shared.providers.conversation_delivery import (
    InMemoryConversationDeliveryStore,
    OutboundDeliveryRecord,
)

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


class _Appender:
    def __init__(self) -> None:
        self.turns: dict[str, BackgroundTaskTurn] = {}
        self.calls = 0

    async def append(self, turn: BackgroundTaskTurn) -> None:
        self.calls += 1
        existing = self.turns.get(turn.turn_id)
        if existing is not None and existing != turn:
            raise AssertionError("a replay MUST NOT rewrite an appended turn")
        self.turns[turn.turn_id] = turn


def _task() -> BackgroundTask:
    return BackgroundTask(
        task_id="task-1",
        owner_principal_id="principal-1",
        origin=BackgroundTaskOrigin(
            conversation_id="conversation-1",
            channel_kind="slack",
            channel_id="channel-1",
            thread_id="thread-1",
            message_id="message-1",
        ),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Investigate the latency regression",
        context_digest="digest-1",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(),
        correlation_id="correlation-1",
        idempotency_key="idempotency-1",
        created_at=NOW,
        retention_until=NOW + timedelta(days=7),
    )


def _attempt(
    *,
    status: BackgroundTaskStatus = BackgroundTaskStatus.SUCCEEDED,
    summary: str | None = "Latency rose after the rollout.",
    terminal_reason: str = "completed",
) -> BackgroundTaskAttempt:
    return BackgroundTaskAttempt(
        attempt_id="attempt-1",
        task=_task(),
        attempt_number=1,
        status=status,
        revision=3,
        updated_at=NOW,
        usage=BackgroundTaskUsage(),
        result=BackgroundTaskResult(
            summary=summary,
            evidence_refs=("evidence-1", "evidence-2"),
            terminal_reason=terminal_reason,
            usage=BackgroundTaskUsage(),
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=30),
        ),
    )


def _sink(appender: _Appender, store: InMemoryConversationDeliveryStore):
    return ConversationCompletionSink(
        appender=appender,
        deliveries=store,
        scope_ref="scope-1",
        binding_id="binding-1",
        clock=lambda: NOW,
    )


async def test_publish_appends_the_turn_and_submits_one_reply() -> None:
    appender = _Appender()
    store = InMemoryConversationDeliveryStore()

    await _sink(appender, store).publish(_attempt())

    (turn,) = appender.turns.values()
    assert turn.text.startswith("[Background task result: completed]")
    assert "Latency rose after the rollout." in turn.text
    assert turn.trusted is False
    assert turn.evidence_refs == ("evidence-1", "evidence-2")
    snapshot = await store.snapshot()
    assert len(snapshot.deliveries) == 1
    assert snapshot.deliveries[0].conversation_id == "conversation-1"
    assert snapshot.deliveries[0].principal_id == "principal-1"


async def test_replay_reuses_the_same_turn_and_delivery() -> None:
    appender = _Appender()
    store = InMemoryConversationDeliveryStore()
    sink = _sink(appender, store)
    attempt = _attempt()

    await sink.publish(attempt)
    await sink.publish(attempt)

    assert appender.calls == 2
    assert len(appender.turns) == 1
    snapshot = await store.snapshot()
    assert len(snapshot.deliveries) == 1


async def test_turn_identifiers_are_deterministic_per_attempt() -> None:
    first = build_turn(_attempt())
    second = build_turn(_attempt())

    assert first == second
    assert first.turn_id.startswith("turn:")
    assert completion_origin_ref(_attempt()) == "background-task:attempt-1"


async def test_sink_never_reruns_the_investigation() -> None:
    appender = _Appender()
    store = InMemoryConversationDeliveryStore()
    attempt = _attempt()

    await _sink(appender, store).publish(attempt)

    (turn,) = appender.turns.values()
    assert turn.attempt_id == attempt.attempt_id
    assert turn.task_id == attempt.task.task_id
    assert attempt.task.prompt not in turn.text


async def test_failed_attempt_still_delivers_a_labeled_answer() -> None:
    appender = _Appender()
    store = InMemoryConversationDeliveryStore()
    attempt = _attempt(
        status=BackgroundTaskStatus.TIMED_OUT,
        summary=None,
        terminal_reason="budget_exhausted",
    )

    await _sink(appender, store).publish(attempt)

    (turn,) = appender.turns.values()
    assert turn.text == "[Background task result: budget_exhausted]"
    snapshot = await store.snapshot()
    assert snapshot.deliveries[0].response.status == "timed_out"


def test_non_terminal_attempt_is_rejected() -> None:
    running = BackgroundTaskAttempt(
        attempt_id="attempt-2",
        task=_task(),
        attempt_number=1,
        status=BackgroundTaskStatus.QUEUED,
        revision=1,
        updated_at=NOW,
    )

    with pytest.raises(CompletionSinkError, match="terminal attempt"):
        build_turn(running)


def test_turn_cannot_be_marked_trusted() -> None:
    turn = build_turn(_attempt())

    with pytest.raises(ValueError, match="untrusted"):
        replace(turn, trusted=True)


async def test_unsupported_channel_kind_fails_closed() -> None:
    appender = _Appender()
    store = InMemoryConversationDeliveryStore()
    attempt = _attempt()
    origin = replace(attempt.task.origin, channel_kind="pager")
    broken = replace(attempt, task=replace(attempt.task, origin=origin))

    with pytest.raises(CompletionSinkError, match="unsupported origin channel kind"):
        await _sink(appender, store).publish(broken)


async def test_delivery_failure_is_recoverable_without_duplicating_the_turn() -> None:
    class _FailingOnceStore(InMemoryConversationDeliveryStore):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def put(self, record: OutboundDeliveryRecord) -> OutboundDeliveryRecord:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("delivery store unavailable")
            return await super().put(record)

    appender = _Appender()
    store = _FailingOnceStore()
    sink = _sink(appender, store)
    attempt = _attempt()

    with pytest.raises(RuntimeError):
        await sink.publish(attempt)
    await sink.publish(attempt)

    assert len(appender.turns) == 1
    snapshot = await store.snapshot()
    assert len(snapshot.deliveries) == 1
