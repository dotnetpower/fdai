from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
    BackgroundTaskConflictError,
    BackgroundTaskCoordinator,
    BackgroundTaskCoordinatorConfig,
    BackgroundTaskKind,
    BackgroundTaskOrigin,
    BackgroundTaskResult,
    BackgroundTaskStatus,
    BackgroundTaskUsage,
    InMemoryBackgroundTaskStore,
    ProgressCallback,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _task(task_id: str, *, wall_seconds: int = 30) -> BackgroundTask:
    return BackgroundTask(
        task_id=task_id,
        owner_principal_id="operator-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        kind=BackgroundTaskKind.READ_ONLY_INVESTIGATION,
        prompt="Inspect bounded evidence.",
        context_digest=f"sha256:{task_id}",
        capability_profile_id="background.read-only",
        budget=BackgroundTaskBudget(max_wall_seconds=wall_seconds),
        correlation_id=f"correlation:{task_id}",
        idempotency_key=f"idempotency:{task_id}",
        created_at=_NOW,
        retention_until=_NOW + timedelta(days=30),
    )


class _Executor:
    def __init__(
        self,
        *,
        delay: float = 0,
        fail: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.delay = delay
        self.fail = fail
        self.clock = clock or (lambda: datetime.now(UTC))
        self.active = 0
        self.max_active = 0
        self.calls = 0

    async def execute(
        self,
        *,
        task: BackgroundTask,
        progress: ProgressCallback,
    ) -> BackgroundTaskResult:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await progress("investigation.started", "Started.", BackgroundTaskUsage())
            await progress(
                "investigation.progress",
                "Collected evidence.",
                BackgroundTaskUsage(tokens=5, tool_calls=1),
            )
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("failed")
            now = self.clock()
            return BackgroundTaskResult(
                summary=f"Completed {task.task_id}.",
                evidence_refs=("evidence:one",),
                terminal_reason="completed",
                usage=BackgroundTaskUsage(tokens=10, tool_calls=1),
                started_at=now,
                finished_at=now,
            )
        finally:
            self.active -= 1


class _Sink:
    def __init__(self) -> None:
        self.attempts: list[BackgroundTaskAttempt] = []

    async def publish(self, attempt: BackgroundTaskAttempt) -> None:
        self.attempts.append(attempt)


class _FlakySink(_Sink):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.retried = asyncio.Event()

    async def publish(self, attempt: BackgroundTaskAttempt) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary delivery failure")
        await super().publish(attempt)
        self.retried.set()


class _NeverReturningSink:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, attempt: BackgroundTaskAttempt) -> None:
        self.calls += 1
        await asyncio.Future()


async def test_coordinator_runs_bounded_tasks_and_persists_before_handoff() -> None:
    store = InMemoryBackgroundTaskStore()
    for index in range(3):
        await store.create(_task(f"background-{index}"))
    executor = _Executor(delay=0.01)
    sink = _Sink()
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=executor,
        completion_sink=sink,
        config=BackgroundTaskCoordinatorConfig(
            coordinator_id="coordinator-one",
            max_concurrency=2,
            progress_interval_seconds=1,
        ),
    )

    first = await coordinator.run_once()
    second = await coordinator.run_once()

    assert len(first) == 2 and len(second) == 1
    assert executor.max_active == 2
    assert all(item.status is BackgroundTaskStatus.SUCCEEDED for item in (*first, *second))
    assert len(sink.attempts) == 3
    for attempt in sink.attempts:
        stored = await store.get(attempt.task.task_id)
        assert stored == attempt and stored.result is not None
        assert len(await store.progress(attempt.task.task_id)) == 2


async def test_completion_retry_does_not_rerun_terminal_task() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task("background-retry"))
    executor = _Executor()
    sink = _FlakySink()
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=executor,
        completion_sink=sink,
        config=BackgroundTaskCoordinatorConfig(coordinator_id="coordinator-retry"),
    )

    completed = await coordinator.run_once()
    assert completed[0].status is BackgroundTaskStatus.SUCCEEDED
    assert executor.calls == 1 and sink.calls == 1

    await asyncio.wait_for(sink.retried.wait(), timeout=2.0)
    assert executor.calls == 1 and sink.calls == 2
    assert sink.attempts == [completed[0]]
    await coordinator.shutdown(drain_seconds=0)


async def test_completion_handoff_timeout_is_bounded_and_retries_without_rerun() -> None:
    now = _NOW

    def clock() -> datetime:
        return now

    store = InMemoryBackgroundTaskStore(clock=clock)
    await store.create(_task("background-timeout"))
    executor = _Executor(clock=clock)
    sink = _NeverReturningSink()
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=executor,
        completion_sink=sink,
        clock=clock,
        config=BackgroundTaskCoordinatorConfig(
            coordinator_id="coordinator-timeout",
            completion_timeout_seconds=0.05,
        ),
    )

    started = perf_counter()
    completed = await coordinator.run_once()
    elapsed = perf_counter() - started

    assert completed[0].status is BackgroundTaskStatus.SUCCEEDED
    assert elapsed < 0.25
    assert executor.calls == 1 and sink.calls == 1

    now += timedelta(seconds=1)
    started = perf_counter()
    assert await coordinator.run_once() == ()
    elapsed = perf_counter() - started

    assert elapsed < 0.25
    assert executor.calls == 1
    assert sink.calls == 2


class _LeaseLostStore(InMemoryBackgroundTaskStore):
    """A store whose lease renewal always conflicts (lease lost mid-flight)."""

    async def renew(self, *args: object, **kwargs: object) -> BackgroundTaskAttempt:
        raise BackgroundTaskConflictError("lease lost mid-flight")


async def test_renew_conflict_hands_off_without_stale_complete() -> None:
    store = _LeaseLostStore()
    await store.create(_task("background-lease-lost"))
    executor = _Executor(delay=1.2)
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=executor,
        config=BackgroundTaskCoordinatorConfig(
            coordinator_id="coordinator-lease-lost",
            lease_seconds=2,
        ),
    )

    # The lease is lost at the first renewal (~1s). The coordinator MUST hand
    # off the durable row instead of completing with a stale revision (which
    # would raise a second conflict the tick could only swallow) or crashing.
    results = await coordinator.run_once()

    assert len(results) == 1
    durable = await store.get("background-lease-lost")
    assert durable is not None
    assert results[0] == durable
    assert results[0].status is not BackgroundTaskStatus.SUCCEEDED


async def test_coordinator_failure_timeout_and_owner_cancel_are_terminal() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task("background-fail"))
    failing = BackgroundTaskCoordinator(
        store=store,
        executor=_Executor(fail=True),
        config=BackgroundTaskCoordinatorConfig(coordinator_id="coordinator-fail"),
    )
    failed = (await failing.run_once())[0]
    assert failed.status is BackgroundTaskStatus.FAILED
    assert failed.result is not None
    assert failed.result.terminal_reason == "executor_error:RuntimeError"

    await store.create(_task("background-cancel"))
    slow = BackgroundTaskCoordinator(
        store=store,
        executor=_Executor(delay=1),
        config=BackgroundTaskCoordinatorConfig(coordinator_id="coordinator-slow"),
    )
    run = asyncio.create_task(slow.run_once())
    await asyncio.sleep(0)
    await slow.cancel("background-cancel", actor="operator-one")
    cancelled = await run
    assert cancelled[0].status is BackgroundTaskStatus.CANCELLED


async def test_shutdown_cancels_after_bounded_drain() -> None:
    store = InMemoryBackgroundTaskStore()
    await store.create(_task("background-shutdown"))
    coordinator = BackgroundTaskCoordinator(
        store=store,
        executor=_Executor(delay=1),
        config=BackgroundTaskCoordinatorConfig(coordinator_id="coordinator-shutdown"),
    )
    run = asyncio.create_task(coordinator.run_once())
    await asyncio.sleep(0)

    await coordinator.shutdown(drain_seconds=0)
    await asyncio.gather(run, return_exceptions=True)

    snapshot = await store.get("background-shutdown")
    assert snapshot is not None
    assert snapshot.status in {BackgroundTaskStatus.RUNNING, BackgroundTaskStatus.UNKNOWN}
