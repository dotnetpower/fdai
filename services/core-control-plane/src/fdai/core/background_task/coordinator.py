"""Bounded coordinator for durable detached background investigations."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Protocol

from fdai.core.background_task.models import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskCompletion,
    BackgroundTaskCompletionState,
    BackgroundTaskProgress,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
)
from fdai.core.background_task.store import (
    BackgroundTaskConflictError,
    BackgroundTaskStore,
)

_LOG = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, BackgroundTaskUsage], Awaitable[None]]


class BackgroundTaskExecutor(Protocol):
    async def execute(
        self,
        *,
        task: BackgroundTask,
        progress: ProgressCallback,
    ) -> BackgroundTaskResult: ...


class BackgroundTaskCompletionSink(Protocol):
    async def publish(self, attempt: BackgroundTaskAttempt) -> None: ...


@dataclass(frozen=True, slots=True)
class BackgroundTaskCoordinatorConfig:
    coordinator_id: str
    max_concurrency: int = 4
    lease_seconds: int = 30
    progress_interval_seconds: float = 1.0
    completion_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.coordinator_id.strip():
            raise ValueError("coordinator_id MUST be non-empty")
        if not 1 <= self.max_concurrency <= 16:
            raise ValueError("max_concurrency MUST be in [1, 16]")
        if not 2 <= self.lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [2, 300]")
        if not 0.05 <= self.progress_interval_seconds <= 60:
            raise ValueError("progress_interval_seconds MUST be in [0.05, 60]")
        if self.completion_timeout_seconds is not None:
            if not 0.05 <= self.completion_timeout_seconds <= 300:
                raise ValueError("completion_timeout_seconds MUST be in [0.05, 300]")
            if self.completion_timeout_seconds > self.lease_seconds:
                raise ValueError("completion_timeout_seconds MUST be <= lease_seconds")


class BackgroundTaskCoordinator:
    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        executor: BackgroundTaskExecutor,
        config: BackgroundTaskCoordinatorConfig,
        completion_sink: BackgroundTaskCompletionSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._config = config
        self._completion_sink = completion_sink
        self._clock = clock or (lambda: datetime.now(UTC))
        self._active: dict[str, asyncio.Task[BackgroundTaskAttempt]] = {}
        self._ticks: set[asyncio.Task[tuple[BackgroundTaskAttempt, ...]]] = set()
        self._completion_retry_due_at: datetime | None = None
        self._completion_retry_task: asyncio.Task[None] | None = None

    def wake(self) -> None:
        tick = asyncio.create_task(self.run_once(), name="background-task-tick")
        self._ticks.add(tick)
        tick.add_done_callback(self._ticks.discard)

    async def run_once(self) -> tuple[BackgroundTaskAttempt, ...]:
        await self._store.reconcile_expired(now=self._clock(), limit=1_000)
        await self._store.reconcile_completion_expired(now=self._clock(), limit=1_000)
        await self._drain_completions()
        started: list[asyncio.Task[BackgroundTaskAttempt]] = []
        task_ids: list[str] = []
        while len(self._active) < self._config.max_concurrency:
            token = secrets.token_urlsafe(24)
            claimed = await self._store.claim_next(
                coordinator=self._config.coordinator_id,
                lease_token=token,
                now=self._clock(),
                lease_seconds=self._config.lease_seconds,
            )
            if claimed is None:
                break
            task = asyncio.create_task(
                self._run_claimed(claimed, token),
                name=f"background-task:{claimed.task.task_id}",
            )
            self._active[claimed.task.task_id] = task
            task.add_done_callback(partial(self._task_done, claimed.task.task_id))
            started.append(task)
            task_ids.append(claimed.task.task_id)
        outcomes = await asyncio.gather(*started, return_exceptions=True)
        results: list[BackgroundTaskAttempt] = []
        for task_id, outcome in zip(task_ids, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                durable = await self._store.get(task_id)
                if durable is not None and durable.status in {
                    BackgroundTaskStatus.CANCELLED,
                    BackgroundTaskStatus.UNKNOWN,
                }:
                    results.append(durable)
                    continue
                raise outcome
            results.append(outcome)
        await self._drain_completions()
        await self._store.purge_retained(now=self._clock(), limit=1_000)
        return tuple(results)

    async def cancel(self, task_id: str, *, actor: str, is_admin: bool = False) -> None:
        await self._store.cancel(
            task_id,
            actor=actor,
            is_admin=is_admin,
            now=self._clock(),
        )
        active = self._active.get(task_id)
        if active is not None and not active.done():
            active.cancel()

    async def shutdown(self, *, drain_seconds: float = 10.0) -> None:
        if drain_seconds < 0:
            raise ValueError("drain_seconds MUST be non-negative")
        delayed = (self._completion_retry_task,) if self._completion_retry_task is not None else ()
        active = (*self._ticks, *self._active.values(), *delayed)
        if not active:
            return
        done, pending = await asyncio.wait(active, timeout=drain_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.gather(*done, return_exceptions=True)

    def _task_done(
        self,
        task_id: str,
        _task: asyncio.Task[BackgroundTaskAttempt],
    ) -> None:
        self._active.pop(task_id, None)

    async def _run_claimed(
        self,
        claimed: BackgroundTaskAttempt,
        lease_token: str,
    ) -> BackgroundTaskAttempt:
        now = max(self._clock(), claimed.updated_at)
        current = await self._store.start(
            claimed.attempt_id,
            expected_revision=claimed.revision,
            lease_token=lease_token,
            now=now,
        )
        reporter = _ProgressReporter(
            store=self._store,
            attempt=current,
            interval_seconds=self._config.progress_interval_seconds,
            clock=self._clock,
        )
        execution = asyncio.create_task(
            self._executor.execute(task=current.task, progress=reporter.publish),
            name=f"background-executor:{current.task.task_id}",
        )
        started_at = now
        renew_interval = self._config.lease_seconds / 2
        try:
            async with asyncio.timeout(current.task.budget.max_wall_seconds):
                while True:
                    done, _ = await asyncio.wait(
                        (execution,),
                        timeout=renew_interval,
                    )
                    if done:
                        result = execution.result()
                        status = BackgroundTaskStatus.SUCCEEDED
                        break
                    try:
                        current = await self._store.renew(
                            current.attempt_id,
                            expected_revision=current.revision,
                            lease_token=lease_token,
                            now=max(self._clock(), current.updated_at),
                            lease_seconds=self._config.lease_seconds,
                            usage=reporter.usage,
                        )
                    except BackgroundTaskConflictError:
                        # Lost the lease: reconcile marked this attempt UNKNOWN
                        # (lease expiry) or another coordinator re-claimed it. We
                        # no longer own it, so cancel local work and hand off the
                        # durable row instead of completing with a stale revision.
                        # That second conflict could only be swallowed by the tick
                        # and would mis-record a lease loss as an executor error.
                        execution.cancel()
                        await asyncio.gather(execution, return_exceptions=True)
                        latest = await self._store.get(current.task.task_id)
                        if latest is not None:
                            return latest
                        raise
        except TimeoutError:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            status = BackgroundTaskStatus.TIMED_OUT
            result = _terminal_result(
                reason="wall_clock_exhausted",
                usage=reporter.usage,
                started_at=started_at,
                finished_at=max(self._clock(), started_at),
            )
        except asyncio.CancelledError:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            latest = await self._store.get(current.task.task_id)
            if latest is not None and latest.status is BackgroundTaskStatus.CANCELLED:
                return latest
            raise
        except Exception as exc:  # noqa: BLE001 - coordinator owns terminal failure shape
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            status = BackgroundTaskStatus.FAILED
            result = _terminal_result(
                reason=f"executor_error:{type(exc).__name__}",
                usage=reporter.usage,
                started_at=started_at,
                finished_at=max(self._clock(), started_at),
            )
        await reporter.flush()
        completed = await self._store.complete(
            current.attempt_id,
            expected_revision=current.revision,
            lease_token=lease_token,
            status=status,
            result=result,
            now=max(result.finished_at, current.updated_at),
        )
        return completed

    async def _drain_completions(self) -> None:
        while True:
            claims = []
            for _ in range(self._config.max_concurrency):
                token = secrets.token_urlsafe(24)
                claimed = await self._store.claim_completion(
                    coordinator=self._config.coordinator_id,
                    lease_token=token,
                    now=self._clock(),
                    lease_seconds=self._config.lease_seconds,
                )
                if claimed is None:
                    break
                claims.append((claimed, token))
            if not claims:
                return
            await asyncio.gather(
                *(self._publish_completion(claim, token) for claim, token in claims)
            )
            if len(claims) < self._config.max_concurrency:
                return

    async def _publish_completion(
        self,
        claim: tuple[BackgroundTaskCompletion, BackgroundTaskAttempt],
        lease_token: str,
    ) -> None:
        completion, attempt = claim
        try:
            if self._completion_sink is not None:
                async with asyncio.timeout(self._completion_publish_timeout_seconds):
                    await self._completion_sink.publish(attempt)
            await self._store.finish_completion(
                attempt.attempt_id,
                lease_token=lease_token,
                delivered=True,
                now=self._clock(),
            )
        except Exception as exc:  # noqa: BLE001 - outbox owns bounded retry
            error_code = f"sink_error:{type(exc).__name__}"
            now = self._clock()
            retry_at = now + timedelta(seconds=min(300, 2 ** max(0, completion.attempt_count - 1)))
            try:
                finished = await self._store.finish_completion(
                    attempt.attempt_id,
                    lease_token=lease_token,
                    delivered=False,
                    now=now,
                    retry_at=retry_at,
                    error_code=error_code,
                )
                if finished.state is BackgroundTaskCompletionState.FAILED and finished.due_at > now:
                    self._schedule_completion_retry(finished.due_at)
            except BackgroundTaskConflictError:
                pass
            _LOG.warning(
                "background_task_completion_handoff_failed",
                extra={"task_id": attempt.task.task_id, "error_code": error_code},
                exc_info=True,
            )

    def _schedule_completion_retry(self, due_at: datetime) -> None:
        if due_at <= self._clock():
            return
        existing = self._completion_retry_task
        existing_due = self._completion_retry_due_at
        if (
            existing is not None
            and not existing.done()
            and existing_due is not None
            and existing_due <= due_at
        ):
            return
        if existing is not None and not existing.done():
            existing.cancel()
        self._completion_retry_due_at = due_at
        task = asyncio.create_task(
            self._run_delayed_completion_retry(due_at),
            name="background-task-completion-retry",
        )
        self._completion_retry_task = task
        task.add_done_callback(self._completion_retry_done)

    def _completion_retry_done(self, task: asyncio.Task[None]) -> None:
        if self._completion_retry_task is task:
            self._completion_retry_task = None
            self._completion_retry_due_at = None
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _LOG.warning(
                "background_task_completion_retry_failed",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def _run_delayed_completion_retry(self, due_at: datetime) -> None:
        delay_seconds = max(0.0, (due_at - self._clock()).total_seconds())
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        await self.run_once()

    @property
    def _completion_publish_timeout_seconds(self) -> float:
        configured = self._config.completion_timeout_seconds
        if configured is not None:
            return configured
        return max(0.05, min(float(self._config.lease_seconds), 1.0))


class _ProgressReporter:
    def __init__(
        self,
        *,
        store: BackgroundTaskStore,
        attempt: BackgroundTaskAttempt,
        interval_seconds: float,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._attempt = attempt
        self._interval = interval_seconds
        self._clock = clock
        self._last_at: datetime | None = None
        self._pending: tuple[str, str, BackgroundTaskUsage] | None = None
        self._sequence = 0
        self._lock = asyncio.Lock()
        self.usage = BackgroundTaskUsage()

    async def publish(
        self,
        kind: str,
        message: str,
        usage: BackgroundTaskUsage,
    ) -> None:
        async with self._lock:
            self.usage = usage
            now = self._clock()
            if self._last_at is not None and (now - self._last_at).total_seconds() < self._interval:
                self._pending = (kind, message, usage)
                return
            await self._append(kind, message, usage, now)

    async def flush(self) -> None:
        async with self._lock:
            if self._pending is None:
                return
            kind, message, usage = self._pending
            self._pending = None
            await self._append(kind, message, usage, self._clock())

    async def _append(
        self,
        kind: str,
        message: str,
        usage: BackgroundTaskUsage,
        at: datetime,
    ) -> None:
        try:
            await self._store.append_progress(
                BackgroundTaskProgress(
                    attempt_id=self._attempt.attempt_id,
                    sequence=self._sequence,
                    kind=kind,
                    message=message,
                    at=at,
                    usage=usage,
                )
            )
        except BackgroundTaskConflictError:
            return
        self._sequence += 1
        self._last_at = at


def _terminal_result(
    *,
    reason: str,
    usage: BackgroundTaskUsage,
    started_at: datetime,
    finished_at: datetime,
) -> BackgroundTaskResult:
    return BackgroundTaskResult(
        summary=None,
        evidence_refs=(),
        terminal_reason=reason,
        usage=usage,
        started_at=started_at,
        finished_at=finished_at,
    )


__all__ = [
    "BackgroundTaskCompletionSink",
    "BackgroundTaskCoordinator",
    "BackgroundTaskCoordinatorConfig",
    "BackgroundTaskExecutor",
    "ProgressCallback",
]
