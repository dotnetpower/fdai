"""Lease/CAS storage seam for durable background task attempts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.background_task.models import (
    TERMINAL_BACKGROUND_STATUSES,
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskLease,
    BackgroundTaskProgress,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)
from fdai.core.background_task.quota import (
    BackgroundTaskQuotaPolicy,
    background_task_quota_time,
    background_task_quota_usage,
    enforce_background_task_quota,
)


class BackgroundTaskConflictError(RuntimeError):
    """A task attempt write lost its expected revision or lease."""


class BackgroundTaskStore(Protocol):
    async def create(
        self,
        task: BackgroundTask,
        *,
        quota: BackgroundTaskQuotaPolicy | None = None,
    ) -> tuple[BackgroundTaskAttempt, bool]: ...

    async def get(
        self,
        task_id: str,
        *,
        owner: str | None = None,
    ) -> BackgroundTaskAttempt | None: ...

    async def list(
        self,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[BackgroundTaskAttempt, ...]: ...

    async def claim_next(
        self,
        *,
        coordinator: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
    ) -> BackgroundTaskAttempt | None: ...

    async def start(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> BackgroundTaskAttempt: ...

    async def renew(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        usage: BackgroundTaskUsage,
    ) -> BackgroundTaskAttempt: ...

    async def complete(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        status: BackgroundTaskStatus,
        result: BackgroundTaskResult,
        now: datetime,
    ) -> BackgroundTaskAttempt: ...

    async def cancel(
        self,
        task_id: str,
        *,
        actor: str,
        is_admin: bool,
        now: datetime,
    ) -> BackgroundTaskAttempt: ...

    async def append_progress(
        self,
        progress: BackgroundTaskProgress,
    ) -> BackgroundTaskProgress: ...

    async def progress(
        self,
        task_id: str,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[BackgroundTaskProgress, ...]: ...

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[BackgroundTaskAttempt, ...]: ...


class InMemoryBackgroundTaskStore:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._attempts: dict[str, BackgroundTaskAttempt] = {}
        self._attempt_by_task: dict[str, str] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._progress: dict[str, list[BackgroundTaskProgress]] = {}
        self._lock = asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(
        self,
        task: BackgroundTask,
        *,
        quota: BackgroundTaskQuotaPolicy | None = None,
    ) -> tuple[BackgroundTaskAttempt, bool]:
        async with self._lock:
            dedup_key = (task.owner_principal_id, task.idempotency_key)
            prior_id = self._idempotency.get(dedup_key)
            if prior_id is not None:
                prior = self._attempts[prior_id]
                if prior.task != task:
                    raise BackgroundTaskConflictError(
                        "background task idempotency key reused with another task"
                    )
                return prior, False
            if task.task_id in self._attempt_by_task:
                raise BackgroundTaskConflictError("background task id already exists")
            if quota is not None:
                quota_now = background_task_quota_time(task, now=self._clock())
                owner_attempts = tuple(
                    attempt
                    for attempt in self._attempts.values()
                    if attempt.task.owner_principal_id == task.owner_principal_id
                )
                enforce_background_task_quota(
                    policy=quota,
                    budget=task.budget,
                    usage=background_task_quota_usage(owner_attempts, now=quota_now),
                )
            attempt = BackgroundTaskAttempt(
                attempt_id=f"{task.task_id}:1",
                task=task,
                attempt_number=1,
                status=BackgroundTaskStatus.QUEUED,
                revision=1,
                updated_at=task.created_at,
            )
            self._attempts[attempt.attempt_id] = attempt
            self._attempt_by_task[task.task_id] = attempt.attempt_id
            self._idempotency[dedup_key] = attempt.attempt_id
            self._progress[attempt.attempt_id] = []
            return attempt, True

    async def get(
        self,
        task_id: str,
        *,
        owner: str | None = None,
    ) -> BackgroundTaskAttempt | None:
        attempt_id = self._attempt_by_task.get(task_id)
        attempt = self._attempts.get(attempt_id) if attempt_id is not None else None
        if attempt is None or (owner is not None and attempt.task.owner_principal_id != owner):
            return None
        return attempt

    async def list(
        self,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[BackgroundTaskAttempt, ...]:
        _limit(limit, 1_000)
        attempts = (
            attempt
            for attempt in self._attempts.values()
            if owner is None or attempt.task.owner_principal_id == owner
        )
        return tuple(
            sorted(
                attempts,
                key=lambda item: (item.updated_at, item.task.task_id),
                reverse=True,
            )[:limit]
        )

    async def claim_next(
        self,
        *,
        coordinator: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
    ) -> BackgroundTaskAttempt | None:
        _lease_input(coordinator, lease_token, now, lease_seconds)
        async with self._lock:
            queued = sorted(
                (
                    attempt
                    for attempt in self._attempts.values()
                    if attempt.status is BackgroundTaskStatus.QUEUED
                ),
                key=lambda item: (item.task.created_at, item.attempt_id),
            )
            if not queued:
                return None
            current = queued[0]
            claimed = replace(
                current,
                status=BackgroundTaskStatus.CLAIMED,
                revision=current.revision + 1,
                updated_at=now,
                lease=BackgroundTaskLease(
                    coordinator,
                    lease_token,
                    now + timedelta(seconds=lease_seconds),
                ),
            )
            self._attempts[current.attempt_id] = claimed
            return claimed

    async def start(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
    ) -> BackgroundTaskAttempt:
        async with self._lock:
            current = self._leased(
                attempt_id,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                statuses=frozenset({BackgroundTaskStatus.CLAIMED}),
            )
            updated = replace(
                current,
                status=BackgroundTaskStatus.RUNNING,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._attempts[attempt_id] = updated
            return updated

    async def renew(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        usage: BackgroundTaskUsage,
    ) -> BackgroundTaskAttempt:
        _lease_input("coordinator", lease_token, now, lease_seconds)
        async with self._lock:
            current = self._leased(
                attempt_id,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                statuses=frozenset({BackgroundTaskStatus.CLAIMED, BackgroundTaskStatus.RUNNING}),
            )
            if current.lease is None:  # pragma: no cover - guarded by _leased
                raise BackgroundTaskConflictError("background task lease is missing")
            updated = replace(
                current,
                revision=current.revision + 1,
                updated_at=now,
                usage=usage,
                lease=replace(
                    current.lease,
                    expires_at=now + timedelta(seconds=lease_seconds),
                ),
            )
            self._attempts[attempt_id] = updated
            return updated

    async def complete(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        status: BackgroundTaskStatus,
        result: BackgroundTaskResult,
        now: datetime,
    ) -> BackgroundTaskAttempt:
        if status not in TERMINAL_BACKGROUND_STATUSES:
            raise ValueError("completion status MUST be terminal")
        async with self._lock:
            current = self._leased(
                attempt_id,
                expected_revision=expected_revision,
                lease_token=lease_token,
                now=now,
                statuses=frozenset({BackgroundTaskStatus.CLAIMED, BackgroundTaskStatus.RUNNING}),
            )
            updated = replace(
                current,
                status=status,
                revision=current.revision + 1,
                updated_at=now,
                lease=None,
                usage=result.usage,
                result=result,
            )
            self._attempts[attempt_id] = updated
            return updated

    async def cancel(
        self,
        task_id: str,
        *,
        actor: str,
        is_admin: bool,
        now: datetime,
    ) -> BackgroundTaskAttempt:
        async with self._lock:
            attempt_id = self._attempt_by_task.get(task_id)
            if attempt_id is None:
                raise LookupError(f"background task {task_id!r} was not found")
            current = self._attempts[attempt_id]
            if actor != current.task.owner_principal_id and not is_admin:
                raise PermissionError("background task cancellation owner mismatch")
            if current.status in TERMINAL_BACKGROUND_STATUSES:
                return current
            started_at = max(current.task.created_at, current.updated_at)
            result = BackgroundTaskResult(
                summary=None,
                evidence_refs=(),
                terminal_reason="cancelled_by_operator",
                usage=current.usage,
                started_at=started_at,
                finished_at=max(now, started_at),
            )
            updated = replace(
                current,
                status=BackgroundTaskStatus.CANCELLED,
                revision=current.revision + 1,
                updated_at=max(now, current.updated_at),
                lease=None,
                result=result,
            )
            self._attempts[attempt_id] = updated
            return updated

    async def append_progress(
        self,
        progress: BackgroundTaskProgress,
    ) -> BackgroundTaskProgress:
        async with self._lock:
            attempt = self._required(progress.attempt_id)
            events = self._progress[progress.attempt_id]
            if len(events) >= attempt.task.budget.max_progress_events:
                raise BackgroundTaskConflictError("background task progress cap reached")
            if progress.sequence != len(events):
                raise BackgroundTaskConflictError("background task progress sequence conflict")
            events.append(progress)
            return progress

    async def progress(
        self,
        task_id: str,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> tuple[BackgroundTaskProgress, ...]:
        _limit(limit, 1_000)
        attempt = await self.get(task_id, owner=owner)
        if attempt is None:
            raise LookupError(f"background task {task_id!r} was not found")
        return tuple(self._progress[attempt.attempt_id][-limit:])

    async def reconcile_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[BackgroundTaskAttempt, ...]:
        _limit(limit, 1_000)
        async with self._lock:
            candidates = sorted(
                (
                    attempt
                    for attempt in self._attempts.values()
                    if attempt.status
                    in {BackgroundTaskStatus.CLAIMED, BackgroundTaskStatus.RUNNING}
                    and attempt.lease is not None
                    and attempt.lease.expires_at <= now
                ),
                key=lambda item: (item.lease.expires_at if item.lease else now, item.attempt_id),
            )[:limit]
            reconciled: list[BackgroundTaskAttempt] = []
            for current in candidates:
                started_at = max(current.task.created_at, current.updated_at)
                result = BackgroundTaskResult(
                    summary=None,
                    evidence_refs=(),
                    terminal_reason="process_lost",
                    usage=current.usage,
                    started_at=started_at,
                    finished_at=max(now, started_at),
                )
                updated = replace(
                    current,
                    status=BackgroundTaskStatus.UNKNOWN,
                    revision=current.revision + 1,
                    updated_at=max(now, current.updated_at),
                    lease=None,
                    result=result,
                )
                self._attempts[current.attempt_id] = updated
                reconciled.append(updated)
            return tuple(reconciled)

    def _leased(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        lease_token: str,
        now: datetime,
        statuses: frozenset[BackgroundTaskStatus],
    ) -> BackgroundTaskAttempt:
        current = self._required(attempt_id)
        if (
            current.revision != expected_revision
            or current.status not in statuses
            or current.lease is None
            or current.lease.token != lease_token
            or current.lease.expires_at <= now
        ):
            raise BackgroundTaskConflictError("background task lease or revision conflict")
        return current

    def _required(self, attempt_id: str) -> BackgroundTaskAttempt:
        try:
            return self._attempts[attempt_id]
        except KeyError as exc:
            raise LookupError(f"background task attempt {attempt_id!r} was not found") from exc


def _lease_input(coordinator: str, lease_token: str, now: datetime, lease_seconds: int) -> None:
    if not coordinator or not lease_token or now.tzinfo is None or not 1 <= lease_seconds <= 300:
        raise ValueError("background task lease input is invalid")


def _limit(value: int, maximum: int) -> None:
    if not 1 <= value <= maximum:
        raise ValueError(f"limit MUST be in [1, {maximum}]")


__all__ = [
    "BackgroundTaskConflictError",
    "BackgroundTaskStore",
    "InMemoryBackgroundTaskStore",
]
