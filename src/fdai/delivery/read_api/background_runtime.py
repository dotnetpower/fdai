"""Composition helpers for durable background investigations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.core.background_task import (
    BackgroundTaskAttempt,
    BackgroundTaskCoordinator,
    BackgroundTaskCoordinatorConfig,
    BackgroundTaskService,
)
from fdai.delivery.persistence import (
    PostgresBackgroundTaskStore,
    PostgresBackgroundTaskStoreConfig,
)
from fdai.delivery.read_api.background_executor import ChatBackendBackgroundTaskExecutor
from fdai.delivery.read_api.routes.background_tasks import BackgroundTaskRoutesConfig
from fdai.delivery.read_api.routes.chat_backend_common import ChatBackend
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


class ConversationBackgroundTaskCompletionSink:
    def __init__(
        self,
        *,
        history: ConversationHistoryStore,
        audit: StateStore,
    ) -> None:
        self._history = history
        self._audit = audit

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


@dataclass(frozen=True, slots=True)
class BackgroundTaskRuntimeGroup:
    routes: BackgroundTaskRoutesConfig
    coordinator: BackgroundTaskCoordinator


def build_background_task_runtime(
    *,
    chat: ChatBackend | None,
    state_store: StateStore,
    conversation_history: ConversationHistoryStore,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    env: Mapping[str, str],
) -> BackgroundTaskRuntimeGroup | None:
    if chat is None:
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
        executor=ChatBackendBackgroundTaskExecutor(backend=chat),
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
    "ConversationBackgroundTaskCompletionSink",
    "StateStoreBackgroundTaskAudit",
    "build_background_task_runtime",
]
