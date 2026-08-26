"""Durable direct and streamed read-investigation coordination."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.read_investigation.execution_policy import ReadInvestigationExecutionMode
from fdai.core.read_investigation.idempotency import (
    ReadInvestigationRunConflictError,
    ReadInvestigationRunMode,
    ReadInvestigationRunRecord,
    ReadInvestigationRunState,
    ReadInvestigationRunStore,
    ReadInvestigationRunUsage,
    read_investigation_request_digest,
    read_investigation_run_id,
)
from fdai.core.read_investigation.models import (
    ReadInvestigationPlan,
    ReadInvestigationRequest,
    ReadInvestigationResult,
)
from fdai.core.read_investigation.planner import plan_read_investigation
from fdai.core.read_investigation.progress import ReadInvestigationProgressKind

Clock = Callable[[], datetime]
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InteractiveReadInvestigationSubmission:
    """Bind one validated Core request to its canonical transport identity."""

    task_id: str
    request: ReadInvestigationRequest

    def __post_init__(self) -> None:
        if self.task_id != read_investigation_run_id(
            self.request.requester_ref,
            self.request.idempotency_key,
        ):
            raise ValueError("interactive task_id MUST match the owner-scoped request identity")


@dataclass(frozen=True, slots=True)
class ReadInvestigationRunProgress:
    """One bounded append-only progress record for owner-scoped replay."""

    task_id: str
    owner_principal_id: str
    sequence: int
    kind: ReadInvestigationProgressKind
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("progress sequence MUST be positive")
        if self.recorded_at.tzinfo is None:
            raise ValueError("progress recorded_at MUST be timezone-aware")


class ReadInvestigationRunProgressStore(Protocol):
    """Append and replay bounded progress without changing run authority."""

    async def append(
        self,
        *,
        task_id: str,
        owner_principal_id: str,
        kind: ReadInvestigationProgressKind,
        recorded_at: datetime,
        limit: int,
    ) -> ReadInvestigationRunProgress: ...

    async def list_after(
        self,
        *,
        task_id: str,
        owner_principal_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[ReadInvestigationRunProgress, ...]: ...


class InMemoryReadInvestigationRunProgressStore:
    """Reference append-only progress store with owner-isolated replay."""

    def __init__(self) -> None:
        self._records: dict[str, list[ReadInvestigationRunProgress]] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        *,
        task_id: str,
        owner_principal_id: str,
        kind: ReadInvestigationProgressKind,
        recorded_at: datetime,
        limit: int,
    ) -> ReadInvestigationRunProgress:
        if not 1 <= limit <= 256:
            raise ValueError("progress limit MUST be in [1, 256]")
        async with self._lock:
            records = self._records.setdefault(task_id, [])
            if records and records[0].owner_principal_id != owner_principal_id:
                raise PermissionError("read investigation progress owner mismatch")
            if len(records) >= limit:
                return records[-1]
            record = ReadInvestigationRunProgress(
                task_id=task_id,
                owner_principal_id=owner_principal_id,
                sequence=len(records) + 1,
                kind=kind,
                recorded_at=recorded_at,
            )
            records.append(record)
            return record

    async def list_after(
        self,
        *,
        task_id: str,
        owner_principal_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[ReadInvestigationRunProgress, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence MUST be non-negative")
        if not 1 <= limit <= 256:
            raise ValueError("progress replay limit MUST be in [1, 256]")
        records = self._records.get(task_id, [])
        if records and records[0].owner_principal_id != owner_principal_id:
            return ()
        return tuple(record for record in records if record.sequence > after_sequence)[:limit]


class InteractiveReadInvestigationExecutor(Protocol):
    """Execute one canonical plan while reporting bounded semantic progress."""

    async def execute(
        self,
        plan: ReadInvestigationPlan,
        *,
        progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
    ) -> ReadInvestigationResult: ...


class InteractiveReadInvestigationModeSelector(Protocol):
    """Select a mode from plan and latency evidence before provider I/O."""

    async def select(self, plan: ReadInvestigationPlan) -> ReadInvestigationExecutionMode: ...


class InteractiveReadInvestigationCompletionSink(Protocol):
    """Accept one terminal run for durable Operator delivery."""

    async def publish(self, record: ReadInvestigationRunRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class InteractiveReadInvestigationConfig:
    """Bound interactive execution, retention, progress, and concurrency."""

    coordinator_id: str
    retention_seconds: int = 30 * 24 * 60 * 60
    terminal_grace_seconds: int = 5
    max_progress_events: int = 32
    max_concurrency: int = 16

    def __post_init__(self) -> None:
        if not self.coordinator_id or len(self.coordinator_id) > 256:
            raise ValueError("coordinator_id MUST be a bounded identifier")
        if self.retention_seconds < 60:
            raise ValueError("retention_seconds MUST be >= 60")
        if not 1 <= self.terminal_grace_seconds <= 60:
            raise ValueError("terminal_grace_seconds MUST be in [1, 60]")
        if not 1 <= self.max_progress_events <= 256:
            raise ValueError("max_progress_events MUST be in [1, 256]")
        if not 1 <= self.max_concurrency <= 256:
            raise ValueError("max_concurrency MUST be in [1, 256]")


@dataclass(slots=True)
class _ActiveRun:
    submission: InteractiveReadInvestigationSubmission
    record: ReadInvestigationRunRecord
    task: asyncio.Task[None] | None = None


class InteractiveReadInvestigationCoordinator:
    """Persist before execution and keep HTTP subscriber lifetime out of run state."""

    def __init__(
        self,
        *,
        store: ReadInvestigationRunStore,
        progress_store: ReadInvestigationRunProgressStore,
        executor: InteractiveReadInvestigationExecutor,
        mode_selector: InteractiveReadInvestigationModeSelector,
        config: InteractiveReadInvestigationConfig,
        completion_sink: InteractiveReadInvestigationCompletionSink | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._progress_store = progress_store
        self._executor = executor
        self._mode_selector = mode_selector
        self._config = config
        self._completion_sink = completion_sink
        self._clock = clock or (lambda: datetime.now(UTC))
        self._active: dict[str, _ActiveRun] = {}
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    async def submit(
        self,
        submission: InteractiveReadInvestigationSubmission,
    ) -> ReadInvestigationExecutionMode:
        """Select a mode and durably claim interactive work before scheduling I/O."""

        plan = plan_read_investigation(submission.request)
        mode = await self._mode_selector.select(plan)
        if mode is ReadInvestigationExecutionMode.DETACHED:
            return mode
        run_mode = ReadInvestigationRunMode(mode.value)
        now = self._clock()
        lease_token = f"lease-{secrets.token_hex(16)}"
        record, created = await self._store.claim(
            owner_principal_id=submission.request.requester_ref,
            request=submission.request,
            mode=run_mode,
            lease_owner=self._config.coordinator_id,
            lease_token=lease_token,
            now=now,
            lease_seconds=(
                submission.request.budget.max_wall_seconds + self._config.terminal_grace_seconds
            ),
            retention_seconds=self._config.retention_seconds,
        )
        if not created:
            if record.state.terminal or submission.task_id in self._active:
                return mode
            if record.state in {
                ReadInvestigationRunState.FAILED,
                ReadInvestigationRunState.EXPIRED,
            }:
                record = await self._store.reclaim(
                    owner_principal_id=record.owner_principal_id,
                    idempotency_key=record.idempotency_key,
                    request_digest=read_investigation_request_digest(submission.request),
                    mode=run_mode,
                    expected_revision=record.revision,
                    lease_owner=self._config.coordinator_id,
                    lease_token=lease_token,
                    now=now,
                    lease_seconds=(
                        submission.request.budget.max_wall_seconds
                        + self._config.terminal_grace_seconds
                    ),
                    retention_seconds=self._config.retention_seconds,
                )
            else:
                return mode
        active = _ActiveRun(submission=submission, record=record)
        task = asyncio.create_task(
            self._execute(active, plan),
            name=f"read-investigation-{submission.task_id}",
        )
        active.task = task
        self._active[submission.task_id] = active
        return mode

    async def cancel(self, task_id: str, *, actor: str, is_admin: bool) -> bool:
        """Record explicit cancellation before stopping local provider work."""

        record = await self._store.get_by_task_id(task_id=task_id)
        if record is None:
            return False
        requested = await self._store.request_cancel(
            task_id=task_id,
            actor=actor,
            is_admin=is_admin,
            now=self._clock(),
        )
        active = self._active.get(task_id)
        if active is None:
            if requested.state is ReadInvestigationRunState.CANCEL_REQUESTED:
                cancelled = await self._store.finish_cancel(
                    owner_principal_id=requested.owner_principal_id,
                    idempotency_key=requested.idempotency_key,
                    expected_revision=requested.revision,
                    lease_token=_lease_token(requested),
                    usage=ReadInvestigationRunUsage(
                        tool_calls=0,
                        execution_duration_ms=0,
                        reserved_cost_microusd=requested.request.budget.max_cost_microusd,
                    ),
                    now=self._clock(),
                )
                await self._publish(cancelled)
            return True
        active.record = requested
        if active.task is not None:
            active.task.cancel()
        return True

    async def reconcile(self) -> tuple[ReadInvestigationRunRecord, ...]:
        """Close expired leases and purge retained terminal runs."""

        now = self._clock()
        reconciled = await self._store.reconcile_expired(now=now)
        await self._store.purge_retained(now=now)
        for record in reconciled:
            await self._publish(record)
        return reconciled

    async def shutdown(self, *, drain_seconds: float) -> None:
        """Drain active runs, then detach without manufacturing cancellation."""

        tasks = tuple(active.task for active in self._active.values() if active.task is not None)
        if not tasks:
            return
        _done, pending = await asyncio.wait(tasks, timeout=max(0.0, drain_seconds))
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _execute(
        self,
        active: _ActiveRun,
        plan: ReadInvestigationPlan,
    ) -> None:
        started_at = self._clock()
        try:
            async with asyncio.timeout(active.record.request.budget.max_wall_seconds):
                await self._semaphore.acquire()
                try:
                    active.record = await self._store.start(
                        owner_principal_id=active.record.owner_principal_id,
                        idempotency_key=active.record.idempotency_key,
                        expected_revision=active.record.revision,
                        lease_token=_lease_token(active.record),
                        now=self._clock(),
                    )

                    async def progress(kind: ReadInvestigationProgressKind) -> None:
                        if active.record.state is ReadInvestigationRunState.CANCEL_REQUESTED:
                            raise asyncio.CancelledError
                        await self._progress_store.append(
                            task_id=active.record.task_id,
                            owner_principal_id=active.record.owner_principal_id,
                            kind=kind,
                            recorded_at=self._clock(),
                            limit=self._config.max_progress_events,
                        )

                    result = await self._executor.execute(
                        plan,
                        progress_observer=progress,
                    )
                finally:
                    self._semaphore.release()
            finished_at = self._clock()
            usage = _usage(active.record.request, result)
            active.record = await self._store.complete(
                owner_principal_id=active.record.owner_principal_id,
                idempotency_key=active.record.idempotency_key,
                expected_revision=active.record.revision,
                lease_token=_lease_token(active.record),
                result=result,
                usage=usage,
                now=finished_at,
            )
            await self._publish(active.record)
        except asyncio.CancelledError:
            if active.record.state is ReadInvestigationRunState.CANCEL_REQUESTED:
                active.record = await self._store.finish_cancel(
                    owner_principal_id=active.record.owner_principal_id,
                    idempotency_key=active.record.idempotency_key,
                    expected_revision=active.record.revision,
                    lease_token=_lease_token(active.record),
                    usage=ReadInvestigationRunUsage(
                        tool_calls=0,
                        execution_duration_ms=_duration_ms(started_at, self._clock()),
                        reserved_cost_microusd=active.record.request.budget.max_cost_microusd,
                    ),
                    now=self._clock(),
                )
                await self._publish(active.record)
            else:
                raise
        except TimeoutError:
            await self._fail(active, started_at, "wall_clock_timeout")
        except Exception as exc:  # noqa: BLE001 - provider details cannot enter the ledger
            _LOG.warning(
                "read_investigation_interactive_failed",
                extra={
                    "correlation_id": active.record.request.correlation_ref,
                    "error_kind": type(exc).__name__,
                },
            )
            await self._fail(active, started_at, "execution_failed")
        finally:
            current = self._active.get(active.record.task_id)
            if current is active:
                self._active.pop(active.record.task_id, None)

    async def _fail(self, active: _ActiveRun, started_at: datetime, reason: str) -> None:
        if active.record.state is ReadInvestigationRunState.CANCEL_REQUESTED:
            return
        try:
            active.record = await self._store.fail(
                owner_principal_id=active.record.owner_principal_id,
                idempotency_key=active.record.idempotency_key,
                expected_revision=active.record.revision,
                lease_token=_lease_token(active.record),
                failure_reason=reason,
                usage=ReadInvestigationRunUsage(
                    tool_calls=0,
                    execution_duration_ms=_duration_ms(started_at, self._clock()),
                    reserved_cost_microusd=active.record.request.budget.max_cost_microusd,
                ),
                now=self._clock(),
            )
        except ReadInvestigationRunConflictError:
            current = await self._store.get_by_task_id(task_id=active.record.task_id)
            if current is None or not current.state.terminal:
                raise
            active.record = current
            return
        await self._publish(active.record)

    async def _publish(self, record: ReadInvestigationRunRecord) -> None:
        if self._completion_sink is not None and record.state.terminal:
            try:
                await self._completion_sink.publish(record)
            except Exception as exc:  # noqa: BLE001 - the durable outbox remains authoritative
                _LOG.warning(
                    "read_investigation_completion_wake_failed",
                    extra={
                        "correlation_id": record.request.correlation_ref,
                        "error_kind": type(exc).__name__,
                    },
                )


def _lease_token(record: ReadInvestigationRunRecord) -> str:
    if record.lease is None:
        raise RuntimeError("active read investigation lost its lease")
    return record.lease.token


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, int((finished_at - started_at).total_seconds() * 1_000))


def _usage(
    request: ReadInvestigationRequest,
    result: ReadInvestigationResult,
) -> ReadInvestigationRunUsage:
    measured = tuple(receipt.cost_microusd for receipt in result.receipts)
    return ReadInvestigationRunUsage(
        tool_calls=len(result.receipts),
        execution_duration_ms=_duration_ms(result.started_at, result.finished_at),
        reserved_cost_microusd=request.budget.max_cost_microusd,
        measured_cost_microusd=(
            sum(cost for cost in measured if cost is not None)
            if all(cost is not None for cost in measured)
            else None
        ),
    )


__all__ = [
    "InMemoryReadInvestigationRunProgressStore",
    "InteractiveReadInvestigationCompletionSink",
    "InteractiveReadInvestigationConfig",
    "InteractiveReadInvestigationCoordinator",
    "InteractiveReadInvestigationSubmission",
    "ReadInvestigationRunProgress",
    "ReadInvestigationRunProgressStore",
]
