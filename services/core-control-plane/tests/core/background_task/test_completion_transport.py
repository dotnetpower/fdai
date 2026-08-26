"""Focused checks for the Core-to-Operator completion publisher."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
    EventBusReadInvestigationCompletionSink,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_COMPLETION_TOPIC,
    ReadInvestigationCompletion,
    read_investigation_task_id,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def record_completed(self, attempt: BackgroundTaskAttempt) -> None:
        self.events.append(f"completed:{attempt.attempt_id}")

    async def record_delivery_enqueued(self, attempt: BackgroundTaskAttempt) -> None:
        self.events.append(f"enqueued:{attempt.attempt_id}")


class _Bus:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> PublishReceipt:
        self.records.append((topic, key, dict(payload)))
        return PublishReceipt(topic, 0, len(self.records) - 1)


def _attempt() -> BackgroundTaskAttempt:
    owner = "principal-one"
    idempotency_key = "request-one"
    task_id = read_investigation_task_id(owner, idempotency_key)
    result = BackgroundTaskResult(
        summary="Bounded terminal result.",
        evidence_refs=("evidence-one",),
        terminal_reason="matched",
        usage=BackgroundTaskUsage(tokens=10, cost_microusd=20, tool_calls=2),
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
    )
    return BackgroundTaskAttempt(
        attempt_id=f"{task_id}:1",
        task=BackgroundTask(
            task_id=task_id,
            owner_principal_id=owner,
            origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
            kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
            prompt="Inspect the resource.",
            context_digest="context-one",
            capability_profile_id="background.read-only",
            budget=BackgroundTaskBudget(),
            correlation_id="correlation-one",
            idempotency_key=idempotency_key,
            created_at=NOW,
            retention_until=NOW + timedelta(days=30),
            accountable_agent="Heimdall",
        ),
        attempt_number=1,
        status=BackgroundTaskStatus.SUCCEEDED,
        revision=3,
        updated_at=NOW + timedelta(seconds=1),
        usage=result.usage,
        result=result,
    )


async def test_completion_publish_is_replay_stable_and_authority_free() -> None:
    audit = _Audit()
    bus = _Bus()
    sink = EventBusReadInvestigationCompletionSink(audit=audit)
    sink.bind(bus)  # type: ignore[arg-type]
    attempt = _attempt()

    await sink.publish(attempt)
    await sink.publish(attempt)

    assert len(bus.records) == 2
    assert bus.records[0] == bus.records[1]
    topic, key, payload = bus.records[0]
    assert topic == READ_INVESTIGATION_COMPLETION_TOPIC
    assert key == attempt.task.task_id
    completion = ReadInvestigationCompletion.model_validate(payload)
    assert completion.execution_authority is False
    assert completion.trusted is False
    assert completion.summary == "Bounded terminal result."
    assert audit.events == [
        f"completed:{attempt.attempt_id}",
        f"enqueued:{attempt.attempt_id}",
        f"completed:{attempt.attempt_id}",
        f"enqueued:{attempt.attempt_id}",
    ]


async def test_completion_publish_requires_bound_bus() -> None:
    audit = _Audit()
    sink = EventBusReadInvestigationCompletionSink(audit=audit)

    with pytest.raises(RuntimeError, match="bus is unavailable"):
        await sink.publish(_attempt())

    assert audit.events == []
