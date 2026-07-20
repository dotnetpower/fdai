from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fdai.core.background_task import (
    BackgroundTask,
    BackgroundTaskAttempt,
    BackgroundTaskBudget,
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
    def __init__(self, *, delay: float = 0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.active = 0
        self.max_active = 0

    async def execute(
        self,
        *,
        task: BackgroundTask,
        progress: ProgressCallback,
    ) -> BackgroundTaskResult:
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
            now = datetime.now(UTC)
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
