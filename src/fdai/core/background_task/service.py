"""Governed operator service for durable background task records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from fdai.core.background_task.models import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
)
from fdai.core.background_task.store import BackgroundTaskStore


class BackgroundTaskAudit(Protocol):
    async def append(self, event: dict[str, object]) -> None: ...


class BackgroundTaskService:
    def __init__(self, *, store: BackgroundTaskStore, audit: BackgroundTaskAudit) -> None:
        self._store = store
        self._audit = audit

    async def create(
        self,
        *,
        owner_principal_id: str,
        origin: BackgroundTaskOrigin,
        prompt: str,
        context_digest: str,
        correlation_id: str,
        idempotency_key: str,
        budget: BackgroundTaskBudget | None = None,
        now: datetime | None = None,
        retention_days: int = 30,
    ) -> tuple[BackgroundTaskAttempt, bool]:
        if not 1 <= retention_days <= 90:
            raise ValueError("retention_days MUST be in [1, 90]")
        created_at = now or datetime.now(UTC)
        task = BackgroundTask(
            task_id=f"background-{uuid4().hex}",
            owner_principal_id=owner_principal_id,
            origin=origin,
            kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
            prompt=prompt,
            context_digest=context_digest,
            capability_profile_id="background.read-only",
            budget=budget or BackgroundTaskBudget(),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            created_at=created_at,
            retention_until=created_at + timedelta(days=retention_days),
        )
        attempt, created = await self._store.create(task)
        if created:
            await self._audit.append(
                {
                    "action_kind": "background-task.created",
                    "task_id": task.task_id,
                    "owner_principal_id": owner_principal_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": idempotency_key,
                    "capability_profile_id": task.capability_profile_id,
                    "created_at": created_at.isoformat(),
                }
            )
        return attempt, created

    async def cancel(
        self,
        task_id: str,
        *,
        actor: str,
        is_admin: bool,
        now: datetime | None = None,
    ) -> BackgroundTaskAttempt:
        cancelled = await self._store.cancel(
            task_id,
            actor=actor,
            is_admin=is_admin,
            now=now or datetime.now(UTC),
        )
        await self._audit.append(
            {
                "action_kind": "background-task.cancelled",
                "task_id": task_id,
                "actor": actor,
                "admin_override": is_admin,
                "status": cancelled.status.value,
            }
        )
        return cancelled


__all__ = ["BackgroundTaskAudit", "BackgroundTaskService"]
