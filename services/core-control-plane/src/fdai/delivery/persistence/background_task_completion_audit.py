"""Atomic completion audit markers for durable background task handoff."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.background_task.models import BackgroundTaskAttempt
from fdai.shared.providers.state_store import StateStore

_SCHEMA_VERSION = "1.0.0"
_KEY_PREFIX = "background-task-completion-audit:"
_COMPLETED = "background-task.completed"
_DELIVERY_ENQUEUED = "background-task.delivery-enqueued"


class BackgroundTaskCompletionAuditConflictError(RuntimeError):
    """A deterministic marker key is bound to different completion evidence."""


@dataclass(frozen=True, slots=True)
class StateStoreBackgroundTaskCompletionAudit:
    """Persist each completion transition and audit entry exactly once."""

    store: StateStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def record_completed(self, attempt: BackgroundTaskAttempt) -> None:
        """Record immutable terminal completion before conversation handoff."""

        await self._record(attempt, action_kind=_COMPLETED)

    async def record_delivery_enqueued(self, attempt: BackgroundTaskAttempt) -> None:
        """Record durable reply-ledger acceptance after the ledger write succeeds."""

        await self._record(attempt, action_kind=_DELIVERY_ENQUEUED)

    async def _record(self, attempt: BackgroundTaskAttempt, *, action_kind: str) -> None:
        result = attempt.result
        if result is None:
            raise ValueError("completion audit requires a terminal background task attempt")
        recorded_at = self.clock()
        if recorded_at.tzinfo is None:
            raise ValueError("completion audit clock MUST be timezone-aware")
        marker = _marker(attempt, action_kind=action_kind, recorded_at=recorded_at)
        key = _marker_key(attempt.attempt_id, action_kind)
        created = await self.store.write_state_with_audit_if_absent(
            key,
            marker,
            _audit_entry(attempt, action_kind=action_kind, recorded_at=recorded_at, key=key),
        )
        if created:
            return
        existing = await self.store.read_state(key)
        if existing is None or _marker_identity(existing) != _marker_identity(marker):
            raise BackgroundTaskCompletionAuditConflictError(
                "background task completion audit marker payload conflict"
            )


def _marker(
    attempt: BackgroundTaskAttempt,
    *,
    action_kind: str,
    recorded_at: datetime,
) -> dict[str, object]:
    result = attempt.result
    if result is None:  # pragma: no cover - guarded by the writer boundary
        raise ValueError("completion audit requires a terminal background task attempt")
    return {
        "schema_version": _SCHEMA_VERSION,
        "revision": 1,
        "action_kind": action_kind,
        "attempt_id": attempt.attempt_id,
        "task_id": attempt.task.task_id,
        "task_revision": attempt.revision,
        "correlation_id": attempt.task.correlation_id,
        "owner_principal_id": attempt.task.owner_principal_id,
        "accountable_agent": attempt.task.accountable_agent,
        "status": attempt.status.value,
        "terminal_reason": result.terminal_reason,
        "result_digest": _result_digest(attempt),
        "recorded_at": recorded_at.isoformat(),
    }


def _marker_identity(marker: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(
        marker.get(field)
        for field in (
            "schema_version",
            "revision",
            "action_kind",
            "attempt_id",
            "task_id",
            "task_revision",
            "correlation_id",
            "owner_principal_id",
            "accountable_agent",
            "status",
            "terminal_reason",
            "result_digest",
        )
    )


def _result_digest(attempt: BackgroundTaskAttempt) -> str:
    result = attempt.result
    if result is None:  # pragma: no cover - guarded by the writer boundary
        raise ValueError("completion audit requires a terminal background task attempt")
    payload = {
        "attempt_id": attempt.attempt_id,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status.value,
        "summary": result.summary,
        "evidence_refs": list(result.evidence_refs),
        "terminal_reason": result.terminal_reason,
        "usage": {
            "tokens": result.usage.tokens,
            "cost_microusd": result.usage.cost_microusd,
            "tool_calls": result.usage.tool_calls,
        },
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "trusted": result.trusted,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _marker_key(attempt_id: str, action_kind: str) -> str:
    return f"{_KEY_PREFIX}{attempt_id}:{action_kind}"


def _audit_entry(
    attempt: BackgroundTaskAttempt,
    *,
    action_kind: str,
    recorded_at: datetime,
    key: str,
) -> dict[str, object]:
    return {
        "event_id": key,
        "correlation_id": attempt.task.correlation_id,
        "idempotency_key": key,
        "actor": "background-task-completion-sink",
        "accountable_agent": attempt.task.accountable_agent,
        "action_kind": action_kind,
        "mode": "shadow",
        "task_id": attempt.task.task_id,
        "attempt_id": attempt.attempt_id,
        "status": attempt.status.value,
        "recorded_at": recorded_at.isoformat(),
    }


__all__ = [
    "BackgroundTaskCompletionAuditConflictError",
    "StateStoreBackgroundTaskCompletionAudit",
]
