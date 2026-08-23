"""Consume versioned read requests into Core-owned background tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.core.background_task import (
    BackgroundReadInvestigationSpec,
    BackgroundTaskBudget,
    BackgroundTaskConflictError,
    BackgroundTaskOrigin,
    BackgroundTaskQuotaExceededError,
    BackgroundTaskService,
)
from fdai.core.read_investigation.intent_spec import read_investigation_intent_spec
from fdai.shared.providers.event_bus import EventBus, subscription
from fdai.shared.providers.read_investigation import ReadInvestigationIntent
from fdai_service_contracts.read_investigation import (
    ReadInvestigationCancellation,
    ReadInvestigationRequest,
    read_investigation_task_id,
)
from pydantic import ValidationError


class ReadInvestigationCoordinatorControl(Protocol):
    """Wake detached work and stop an active task after durable cancellation."""

    def wake(self) -> None: ...

    async def cancel(
        self,
        task_id: str,
        *,
        actor: str,
        is_admin: bool,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ReadInvestigationConsumerBinding:
    """Bind one request topic to durable task creation and coordinator wakeup."""

    request_topic: str
    group_id: str
    service: BackgroundTaskService
    coordinator: ReadInvestigationCoordinatorControl

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Consume until the shared Core stop event is set."""

        await consume_read_investigations(
            bus=bus,
            topic=self.request_topic,
            group_id=self.group_id,
            service=self.service,
            coordinator=self.coordinator,
            stop=stop,
        )


async def consume_read_investigations(
    *,
    bus: EventBus,
    topic: str,
    group_id: str,
    service: BackgroundTaskService,
    coordinator: ReadInvestigationCoordinatorControl,
    stop: asyncio.Event,
) -> None:
    """Persist valid requests before allowing at-least-once delivery to advance."""

    async with subscription(bus, topic, group_id) as stream:
        async for envelope in stream:
            if stop.is_set():
                return
            if envelope.payload.get("command") == "cancel":
                await _consume_cancellation(
                    bus=bus,
                    envelope=envelope,
                    service=service,
                    coordinator=coordinator,
                )
                continue
            try:
                request = ReadInvestigationRequest.model_validate(envelope.payload)
                if envelope.key != read_investigation_task_id(
                    request.owner_principal_id,
                    request.idempotency_key,
                ):
                    raise ValueError("read investigation partition key mismatch")
            except (ValidationError, ValueError):
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "read_investigation_request_rejected",
                )
                continue
            try:
                await service.create(
                    owner_principal_id=request.owner_principal_id,
                    origin=BackgroundTaskOrigin(
                        conversation_id=request.origin.conversation_id,
                        channel_kind=request.origin.channel_kind,
                        channel_id=request.origin.channel_id,
                        thread_id=request.origin.thread_id,
                        message_id=request.origin.message_id,
                    ),
                    prompt=request.prompt,
                    context_digest=request.request_digest,
                    correlation_id=request.correlation_id,
                    idempotency_key=request.idempotency_key,
                    budget=BackgroundTaskBudget(
                        max_wall_seconds=request.budget.max_wall_seconds,
                        max_tokens=request.budget.max_tokens,
                        max_cost_microusd=request.budget.max_cost_microusd,
                        max_tool_calls=request.budget.max_tool_calls,
                        max_progress_events=request.budget.max_progress_events,
                    ),
                    investigation=BackgroundReadInvestigationSpec(
                        intent=ReadInvestigationIntent(request.intent.value),
                        resource_name=request.selector.name,
                        resource_type=request.selector.resource_type,
                        resource_group=request.selector.resource_group,
                        scope_ref="scope:configured-reader",
                        lookback_seconds=read_investigation_intent_spec(
                            ReadInvestigationIntent(request.intent.value)
                        ).lookback_seconds,
                        explicit_deep=request.explicit_deep,
                    ),
                )
            except BackgroundTaskConflictError:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "read_investigation_idempotency_conflict",
                )
                continue
            except BackgroundTaskQuotaExceededError:
                await bus.dead_letter(
                    envelope.topic,
                    envelope.key,
                    envelope.payload,
                    "read_investigation_quota_denied",
                )
                continue
            coordinator.wake()


async def _consume_cancellation(
    *,
    bus: EventBus,
    envelope: Any,
    service: BackgroundTaskService,
    coordinator: ReadInvestigationCoordinatorControl,
) -> None:
    try:
        cancellation = ReadInvestigationCancellation.model_validate(envelope.payload)
        if envelope.key != cancellation.task_id:
            raise ValueError("read investigation cancellation partition key mismatch")
    except (ValidationError, ValueError):
        await bus.dead_letter(
            envelope.topic,
            envelope.key,
            envelope.payload,
            "read_investigation_cancellation_rejected",
        )
        return
    try:
        await service.cancel(
            cancellation.task_id,
            actor=cancellation.owner_principal_id,
            is_admin=cancellation.admin_override,
        )
        await coordinator.cancel(
            cancellation.task_id,
            actor=cancellation.owner_principal_id,
            is_admin=cancellation.admin_override,
        )
    except (LookupError, PermissionError):
        await bus.dead_letter(
            envelope.topic,
            envelope.key,
            envelope.payload,
            "read_investigation_cancellation_denied",
        )


__all__ = [
    "ReadInvestigationConsumerBinding",
    "ReadInvestigationCoordinatorControl",
    "consume_read_investigations",
]
