"""Composition helpers for durable background investigations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai.core.background_task import (
    BackgroundTaskAttempt,
    BackgroundTaskCoordinator,
    BackgroundTaskCoordinatorConfig,
    BackgroundTaskExecutor,
    BackgroundTaskService,
)
from fdai.core.conversation.principal_binding import PrincipalConversationBindingStore
from fdai.delivery.persistence import (
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
)
from fdai.delivery.read_api.routes.background_tasks import BackgroundTaskRoutesConfig
from fdai.shared.providers.conversation_channel import (
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.conversation_delivery import (
    OutboundDeliveryRecord,
    PrincipalConversationBindingState,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRecord,
    ConversationTurnRole,
)


class StateStoreBackgroundTaskAudit:
    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def append(self, event: dict[str, object]) -> None:
        await self._store.append_audit_entry(event)


class BackgroundOutboundDelivery(Protocol):
    async def submit(
        self,
        *,
        origin_ref: str,
        principal_id: str,
        scope_ref: str,
        conversation_id: str,
        binding_id: str | None,
        response: OutboundResponse,
        send_immediately: bool = True,
    ) -> OutboundDeliveryRecord: ...


@dataclass(frozen=True, slots=True)
class BackgroundCompletionDeliveryContext:
    scope_ref: str
    binding_id: str
    channel_kind: ConversationChannelKind


class BackgroundCompletionBindingResolver:
    def __init__(self, *, bindings: PrincipalConversationBindingStore) -> None:
        self._bindings = bindings

    async def resolve(
        self,
        attempt: BackgroundTaskAttempt,
    ) -> BackgroundCompletionDeliveryContext | None:
        origin = attempt.task.origin
        try:
            channel_kind = ConversationChannelKind(origin.channel_kind)
        except ValueError:
            return None
        matches = [
            binding
            for binding in await self._bindings.list_for_principal(
                principal_id=attempt.task.owner_principal_id
            )
            if binding.state is PrincipalConversationBindingState.ACTIVE
            and binding.conversation_id == origin.conversation_id
            and binding.endpoint.channel_kind is channel_kind
            and binding.endpoint.channel_id == origin.channel_id
            and binding.endpoint.thread_id == origin.thread_id
        ]
        if len(matches) != 1:
            return None
        binding = matches[0]
        return BackgroundCompletionDeliveryContext(
            scope_ref=binding.scope_ref,
            binding_id=binding.binding_id,
            channel_kind=channel_kind,
        )


class ConversationBackgroundTaskCompletionSink:
    def __init__(
        self,
        *,
        history: ConversationHistoryStore,
        audit: StateStore,
        outbound_delivery: BackgroundOutboundDelivery | None = None,
        binding_resolver: BackgroundCompletionBindingResolver | None = None,
    ) -> None:
        self._history = history
        self._audit = audit
        self._outbound_delivery = outbound_delivery
        self._binding_resolver = binding_resolver

    async def publish(self, attempt: BackgroundTaskAttempt) -> None:
        result = attempt.result
        if result is None:
            raise ValueError("background completion requires a terminal result")
        content = result.summary or f"Background task ended: {result.terminal_reason}"
        await self._audit.append_audit_entry(
            {
                "action_kind": "background-task.completed",
                "task_id": attempt.task.task_id,
                "attempt_id": attempt.attempt_id,
                "owner_principal_id": attempt.task.owner_principal_id,
                "correlation_id": attempt.task.correlation_id,
                "status": attempt.status.value,
                "terminal_reason": result.terminal_reason,
                "tokens": result.usage.tokens,
                "cost_microusd": result.usage.cost_microusd,
                "tool_calls": result.usage.tool_calls,
                "finished_at": result.finished_at.isoformat(),
            }
        )
        await self._history.append_turn(
            ConversationTurnRecord(
                turn_id=f"background:{attempt.attempt_id}",
                conversation_id=attempt.task.origin.conversation_id,
                principal_id=attempt.task.owner_principal_id,
                turn_index=0,
                role=ConversationTurnRole.ASSISTANT,
                content=f"[Background task result: {attempt.task.task_id}]\n{content}",
                recorded_at=result.finished_at,
                idempotency_key=f"background-completion:{attempt.attempt_id}",
                metadata={
                    "source": "background-task",
                    "task_id": attempt.task.task_id,
                    "attempt_id": attempt.attempt_id,
                    "correlation_id": attempt.task.correlation_id,
                    "status": attempt.status.value,
                    "trusted": "false",
                },
            ),
            allocate_index=True,
        )
        if self._outbound_delivery is None or self._binding_resolver is None:
            return
        context = await self._binding_resolver.resolve(attempt)
        if context is None or attempt.task.origin.message_id is None:
            raise ValueError("background completion has no verified delivery context")
        delivery = await self._outbound_delivery.submit(
            origin_ref=f"background:{attempt.attempt_id}",
            principal_id=attempt.task.owner_principal_id,
            scope_ref=context.scope_ref,
            conversation_id=attempt.task.origin.conversation_id,
            binding_id=context.binding_id,
            response=OutboundResponse(
                channel_kind=context.channel_kind,
                channel_id=attempt.task.origin.channel_id,
                in_reply_to=attempt.task.origin.message_id,
                thread_id=attempt.task.origin.thread_id,
                status=attempt.status.value,
                text=content,
                data={
                    "source": "background-task",
                    "task_id": attempt.task.task_id,
                    "attempt_id": attempt.attempt_id,
                    "correlation_id": attempt.task.correlation_id,
                    "trusted": False,
                },
                evidence_refs=result.evidence_refs,
            ),
            send_immediately=False,
        )
        await self._audit.append_audit_entry(
            {
                "action_kind": "background-task.delivery-enqueued",
                "task_id": attempt.task.task_id,
                "attempt_id": attempt.attempt_id,
                "correlation_id": attempt.task.correlation_id,
                "delivery_id": delivery.delivery_id,
                "delivery_state": delivery.state.value,
            }
        )


@dataclass(frozen=True, slots=True)
class BackgroundTaskRuntimeGroup:
    routes: BackgroundTaskRoutesConfig
    coordinator: BackgroundTaskCoordinator


def build_background_task_runtime(
    *,
    executor: BackgroundTaskExecutor | None,
    state_store: StateStore,
    conversation_history: ConversationHistoryStore,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    env: Mapping[str, str],
    outbound_delivery: BackgroundOutboundDelivery | None = None,
    binding_store: PrincipalConversationBindingStore | None = None,
) -> BackgroundTaskRuntimeGroup | None:
    if executor is None:
        return None
    store = PostgresBackgroundTaskStore(
        config=PostgresBackgroundTaskStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=executor,
        config=BackgroundTaskCoordinatorConfig(
            coordinator_id=env.get("HOSTNAME", "fdai-background").strip() or "fdai-background",
            max_concurrency=_int(env, "FDAI_BACKGROUND_MAX_CONCURRENCY", 4, 1, 16),
            lease_seconds=_int(env, "FDAI_BACKGROUND_LEASE_SECONDS", 30, 2, 300),
            progress_interval_seconds=float(
                env.get("FDAI_BACKGROUND_PROGRESS_INTERVAL_SECONDS", "1.0")
            ),
        ),
        completion_sink=ConversationBackgroundTaskCompletionSink(
            history=conversation_history,
            audit=state_store,
            outbound_delivery=outbound_delivery,
            binding_resolver=(
                BackgroundCompletionBindingResolver(bindings=binding_store)
                if binding_store is not None
                else None
            ),
        ),
    )
    service = BackgroundTaskService(
        store=store,
        audit=StateStoreBackgroundTaskAudit(store=state_store),
    )
    return BackgroundTaskRuntimeGroup(
        routes=BackgroundTaskRoutesConfig(
            service=service,
            store=store,
            coordinator=coordinator,
        ),
        coordinator=coordinator,
    )


def _int(
    env: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} MUST be in [{minimum}, {maximum}]")
    return value


__all__ = [
    "BackgroundTaskRuntimeGroup",
    "BackgroundCompletionBindingResolver",
    "BackgroundCompletionDeliveryContext",
    "BackgroundOutboundDelivery",
    "ConversationBackgroundTaskCompletionSink",
    "StateStoreBackgroundTaskAudit",
    "build_background_task_runtime",
]
