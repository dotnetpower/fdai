"""Idempotent lifecycle audit markers for durable background tasks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from fdai.shared.providers.state_store import StateStore

_KEY_PREFIX = "background-task-lifecycle-audit:"
_ALLOWED_ACTIONS = frozenset({"background-task.created", "background-task.cancelled"})


class BackgroundTaskLifecycleAuditConflictError(RuntimeError):
    """A deterministic lifecycle marker is bound to different evidence."""


@dataclass(frozen=True, slots=True)
class StateStoreBackgroundTaskLifecycleAudit:
    """Persist one lifecycle marker and matching audit entry atomically."""

    store: StateStore

    async def append(self, event: dict[str, object]) -> None:
        action_kind = event.get("action_kind")
        task_id = event.get("task_id")
        if action_kind not in _ALLOWED_ACTIONS:
            raise ValueError("unsupported background task lifecycle audit action")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("background task lifecycle audit requires task_id")
        marker = {"schema_version": "1.0.0", **event}
        digest = _event_digest(marker)
        key = f"{_KEY_PREFIX}{digest}"
        created = await self.store.write_state_with_audit_if_absent(
            key,
            marker,
            {
                "event_id": key,
                "idempotency_key": key,
                "actor": "background-task-service",
                "accountable_agent": event.get("accountable_agent"),
                "action_kind": action_kind,
                "mode": "shadow",
                "task_id": task_id,
                "correlation_id": event.get("correlation_id"),
            },
        )
        if created:
            return
        existing = await self.store.read_state(key)
        if not isinstance(existing, Mapping) or _event_digest(existing) != digest:
            raise BackgroundTaskLifecycleAuditConflictError(
                "background task lifecycle audit marker payload conflict"
            )


def _event_digest(event: Mapping[str, object]) -> str:
    encoded = json.dumps(
        event,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "BackgroundTaskLifecycleAuditConflictError",
    "StateStoreBackgroundTaskLifecycleAudit",
]
