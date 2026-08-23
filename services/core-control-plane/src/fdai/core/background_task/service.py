"""Governed operator service for durable background task records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_service_contracts.read_investigation import read_investigation_task_id

from fdai.core.background_task.models import (
    BACKGROUND_TASK_ACCOUNTABLE_AGENT,
    BackgroundReadInvestigationSpec,
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
)
from fdai.core.background_task.quota import BackgroundTaskQuotaPolicy
from fdai.core.background_task.store import BackgroundTaskStore


class BackgroundTaskAudit(Protocol):
    async def append(self, event: dict[str, object]) -> None: ...


class BackgroundTaskService:
    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        audit: BackgroundTaskAudit,
        quota_policy: BackgroundTaskQuotaPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._audit = audit
        self._quota_policy = quota_policy or BackgroundTaskQuotaPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))

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
        investigation: BackgroundReadInvestigationSpec | None = None,
        now: datetime | None = None,
        retention_days: int = 30,
    ) -> tuple[BackgroundTaskAttempt, bool]:
        if not 1 <= retention_days <= 90:
            raise ValueError("retention_days MUST be in [1, 90]")
        created_at = now or self._clock()
        task = BackgroundTask(
            task_id=_task_id(owner_principal_id, idempotency_key),
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
            investigation=investigation,
            accountable_agent=BACKGROUND_TASK_ACCOUNTABLE_AGENT,
        )
        attempt, created = await self._store.create(
            task,
            quota=self._quota_policy,
            requires_creation_audit=True,
        )
        audited = await self._store.creation_audited(task.task_id)
        if audited is None:  # pragma: no cover - store create contract
            raise RuntimeError("created background task is unavailable")
        if not audited:
            await self._audit.append(
                {
                    "action_kind": "background-task.created",
                    "task_id": task.task_id,
                    "owner_principal_id": owner_principal_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": idempotency_key,
                    "capability_profile_id": task.capability_profile_id,
                    "accountable_agent": task.accountable_agent,
                    "created_at": created_at.isoformat(),
                }
            )
            attempt = await self._store.mark_creation_audited(
                task.task_id,
                now=self._clock(),
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
            now=now or self._clock(),
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


def _task_id(owner_principal_id: str, idempotency_key: str) -> str:
    return read_investigation_task_id(owner_principal_id, idempotency_key)


__all__ = ["BackgroundTaskAudit", "BackgroundTaskService"]
