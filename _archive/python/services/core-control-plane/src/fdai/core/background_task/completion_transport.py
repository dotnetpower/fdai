"""Publish terminal read-investigation completions through the event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_COMPLETION_TOPIC,
    ReadInvestigationCompletionUsage,
    ReadInvestigationOrigin,
    build_read_investigation_completion,
)

from fdai.core.background_task.completion_sink import CompletionAuditWriter
from fdai.core.background_task.models import (
    BackgroundTaskAttempt,
    BackgroundTaskStatus,
)
from fdai.shared.providers.event_bus import EventBus

CompletionStatus = Literal["succeeded", "failed", "cancelled", "timed_out", "unknown"]
_COMPLETION_STATUSES: dict[BackgroundTaskStatus, CompletionStatus] = {
    BackgroundTaskStatus.SUCCEEDED: "succeeded",
    BackgroundTaskStatus.FAILED: "failed",
    BackgroundTaskStatus.CANCELLED: "cancelled",
    BackgroundTaskStatus.TIMED_OUT: "timed_out",
    BackgroundTaskStatus.UNKNOWN: "unknown",
}


@dataclass(slots=True)
class EventBusReadInvestigationCompletionSink:
    """Transfer one immutable completion and close only after broker acceptance."""

    audit: CompletionAuditWriter
    topic: str = READ_INVESTIGATION_COMPLETION_TOPIC
    _bus: EventBus | None = field(default=None, init=False, repr=False)

    def bind(self, bus: EventBus) -> None:
        """Bind the runtime-owned bus before the coordinator can execute."""

        self._bus = bus

    def unbind(self) -> None:
        """Drop the runtime bus during bounded shutdown."""

        self._bus = None

    async def publish(self, attempt: BackgroundTaskAttempt) -> None:
        """Publish a bounded completion; retries retain the same identity and payload."""

        bus = self._bus
        if bus is None:
            raise RuntimeError("read investigation completion bus is unavailable")
        result = attempt.result
        if result is None:
            raise ValueError("read investigation completion requires a terminal result")
        try:
            status = _COMPLETION_STATUSES[attempt.status]
        except KeyError as exc:
            raise ValueError("read investigation completion requires terminal status") from exc
        task = attempt.task
        completion = build_read_investigation_completion(
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            attempt_number=attempt.attempt_number,
            owner_principal_id=task.owner_principal_id,
            request_idempotency_key=task.idempotency_key,
            correlation_id=task.correlation_id,
            origin=ReadInvestigationOrigin(
                conversation_id=task.origin.conversation_id,
                channel_kind=task.origin.channel_kind,
                channel_id=task.origin.channel_id,
                thread_id=task.origin.thread_id,
                message_id=task.origin.message_id,
            ),
            status=status,
            terminal_reason=result.terminal_reason,
            summary=result.summary,
            evidence_refs=result.evidence_refs,
            usage=ReadInvestigationCompletionUsage(
                tokens=result.usage.tokens,
                cost_microusd=result.usage.cost_microusd,
                tool_calls=result.usage.tool_calls,
            ),
            started_at=result.started_at,
            finished_at=result.finished_at,
            completed_at=attempt.updated_at,
            retention_until=task.retention_until,
        )
        await self.audit.record_completed(attempt)
        await bus.publish(
            self.topic,
            task.task_id,
            completion.model_dump(mode="json"),
        )
        await self.audit.record_delivery_enqueued(attempt)


__all__ = ["EventBusReadInvestigationCompletionSink"]
