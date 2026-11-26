from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from fdai.core.read_investigation import (
    InMemoryReadInvestigationRunProgressStore,
    InMemoryReadInvestigationRunStore,
    InteractiveReadInvestigationConfig,
    InteractiveReadInvestigationCoordinator,
    InteractiveReadInvestigationSubmission,
    ReadInvestigationBudget,
    ReadInvestigationExecutionMode,
    ReadInvestigationOutcome,
    ReadInvestigationPlan,
    ReadInvestigationProgressKind,
    ReadInvestigationRequest,
    ReadInvestigationResult,
    ReadInvestigationRunState,
    ReadInvestigationRunUsage,
    read_investigation_run_id,
)
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ResourceResolution,
    ResourceResolutionStatus,
    ResourceSelector,
)

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _request(
    *,
    idempotency_key: str = "idempotency-one",
    max_wall_seconds: int = 30,
) -> ReadInvestigationRequest:
    return ReadInvestigationRequest(
        requester_ref="principal-one",
        conversation_ref="conversation-one",
        correlation_ref="correlation-one",
        intent=ReadInvestigationIntent.RESOURCE_STATE,
        selector=ResourceSelector(name="resource-one", scope_ref="scope:configured-reader"),
        lookback_seconds=3_600,
        requested_evidence=(),
        budget=ReadInvestigationBudget(max_wall_seconds=max_wall_seconds),
        idempotency_key=idempotency_key,
        created_at=NOW,
    )


def _submission(
    *,
    idempotency_key: str = "idempotency-one",
    max_wall_seconds: int = 30,
) -> InteractiveReadInvestigationSubmission:
    request = _request(
        idempotency_key=idempotency_key,
        max_wall_seconds=max_wall_seconds,
    )
    return InteractiveReadInvestigationSubmission(
        task_id=read_investigation_run_id(request.requester_ref, request.idempotency_key),
        request=request,
    )


class _Selector:
    async def select(self, _plan: object) -> ReadInvestigationExecutionMode:
        return ReadInvestigationExecutionMode.STREAMED


class _Executor:
    def __init__(self, *, blocker: asyncio.Event | None = None) -> None:
        self.calls = 0
        self.blocker = blocker

    async def execute(
        self,
        plan: ReadInvestigationPlan,
        *,
        progress_observer: Callable[[ReadInvestigationProgressKind], Awaitable[None]] | None = None,
    ) -> ReadInvestigationResult:
        self.calls += 1
        observer = progress_observer
        assert observer is not None
        await observer(ReadInvestigationProgressKind.PLANNED)
        if self.blocker is not None:
            await self.blocker.wait()
        await observer(ReadInvestigationProgressKind.COMPLETED)
        request = plan.request
        return ReadInvestigationResult(
            request=request,
            outcome=ReadInvestigationOutcome.NONE,
            resolution=ResourceResolution(
                status=ResourceResolutionStatus.NOT_FOUND,
                detail="resource was not found",
            ),
            evidence=(),
            receipts=(),
            progress_kinds=(
                ReadInvestigationProgressKind.PLANNED.value,
                ReadInvestigationProgressKind.COMPLETED.value,
            ),
            started_at=NOW,
            finished_at=NOW,
        )


class _Sink:
    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[object] = []
        self.event = asyncio.Event()
        self.fail = fail

    async def publish(self, record: object) -> None:
        if self.fail:
            raise RuntimeError("wake unavailable")
        self.records.append(record)
        self.event.set()


def _coordinator(
    *,
    run_store: InMemoryReadInvestigationRunStore,
    progress_store: InMemoryReadInvestigationRunProgressStore,
    executor: _Executor,
    sink: _Sink,
    max_concurrency: int = 16,
) -> InteractiveReadInvestigationCoordinator:
    return InteractiveReadInvestigationCoordinator(
        store=run_store,
        progress_store=progress_store,
        executor=executor,
        mode_selector=_Selector(),
        config=InteractiveReadInvestigationConfig(
            coordinator_id="core-one",
            max_concurrency=max_concurrency,
        ),
        completion_sink=sink,
        clock=lambda: NOW,
    )


async def test_submit_claims_once_and_persists_progress_before_completion() -> None:
    run_store = InMemoryReadInvestigationRunStore()
    progress_store = InMemoryReadInvestigationRunProgressStore()
    executor = _Executor()
    sink = _Sink()
    coordinator = _coordinator(
        run_store=run_store,
        progress_store=progress_store,
        executor=executor,
        sink=sink,
    )
    submission = _submission()

    first = await coordinator.submit(submission)
    second = await coordinator.submit(submission)
    await asyncio.wait_for(sink.event.wait(), timeout=1.0)

    record = await run_store.get_by_task_id(task_id=submission.task_id)
    progress = await progress_store.list_after(
        task_id=submission.task_id,
        owner_principal_id=submission.request.requester_ref,
        after_sequence=0,
        limit=32,
    )
    assert first is ReadInvestigationExecutionMode.STREAMED
    assert second is ReadInvestigationExecutionMode.STREAMED
    assert executor.calls == 1
    assert record is not None and record.state is ReadInvestigationRunState.COMPLETED
    assert [item.kind for item in progress] == [
        ReadInvestigationProgressKind.PLANNED,
        ReadInvestigationProgressKind.COMPLETED,
    ]
    assert len(sink.records) == 1


async def test_explicit_cancel_enforces_owner_and_stops_active_execution() -> None:
    run_store = InMemoryReadInvestigationRunStore()
    progress_store = InMemoryReadInvestigationRunProgressStore()
    executor = _Executor(blocker=asyncio.Event())
    sink = _Sink()
    coordinator = _coordinator(
        run_store=run_store,
        progress_store=progress_store,
        executor=executor,
        sink=sink,
    )
    submission = _submission()
    await coordinator.submit(submission)
    await asyncio.sleep(0)

    with pytest.raises(PermissionError, match="not authorized"):
        await coordinator.cancel(submission.task_id, actor="principal-two", is_admin=False)
    assert await coordinator.cancel(
        submission.task_id,
        actor="principal-one",
        is_admin=False,
    )
    await asyncio.wait_for(sink.event.wait(), timeout=1.0)

    record = await run_store.get_by_task_id(task_id=submission.task_id)
    assert record is not None and record.state is ReadInvestigationRunState.CANCELLED
    assert record.failure_reason == "cancelled_by_owner"


async def test_concurrency_queue_wait_consumes_wall_clock_budget() -> None:
    run_store = InMemoryReadInvestigationRunStore()
    progress_store = InMemoryReadInvestigationRunProgressStore()
    executor = _Executor(blocker=asyncio.Event())
    sink = _Sink()
    coordinator = _coordinator(
        run_store=run_store,
        progress_store=progress_store,
        executor=executor,
        sink=sink,
        max_concurrency=1,
    )
    first = _submission(idempotency_key="first", max_wall_seconds=30)
    second = _submission(idempotency_key="second", max_wall_seconds=1)
    await coordinator.submit(first)
    await asyncio.sleep(0)

    await coordinator.submit(second)
    await asyncio.wait_for(sink.event.wait(), timeout=2.0)

    second_record = await run_store.get_by_task_id(task_id=second.task_id)
    assert executor.calls == 1
    assert second_record is not None
    assert second_record.state is ReadInvestigationRunState.FAILED
    assert second_record.failure_reason == "wall_clock_timeout"
    await coordinator.cancel(first.task_id, actor="principal-one", is_admin=False)


async def test_completion_wake_failure_cannot_rewrite_terminal_run() -> None:
    run_store = InMemoryReadInvestigationRunStore()
    submission = _submission()
    coordinator = _coordinator(
        run_store=run_store,
        progress_store=InMemoryReadInvestigationRunProgressStore(),
        executor=_Executor(),
        sink=_Sink(fail=True),
    )

    await coordinator.submit(submission)
    for _ in range(10):
        await asyncio.sleep(0)
        record = await run_store.get_by_task_id(task_id=submission.task_id)
        if record is not None and record.state.terminal:
            break

    assert record is not None
    assert record.state is ReadInvestigationRunState.COMPLETED
    assert record.failure_reason is None


async def test_late_executor_completion_respects_cross_replica_cancellation() -> None:
    run_store = InMemoryReadInvestigationRunStore()
    blocker = asyncio.Event()
    sink = _Sink()
    submission = _submission()
    coordinator = _coordinator(
        run_store=run_store,
        progress_store=InMemoryReadInvestigationRunProgressStore(),
        executor=_Executor(blocker=blocker),
        sink=sink,
    )
    await coordinator.submit(submission)
    await asyncio.sleep(0)
    requested = await run_store.request_cancel(
        task_id=submission.task_id,
        actor="principal-one",
        is_admin=False,
        now=NOW,
    )
    cancelled = await run_store.finish_cancel(
        owner_principal_id=requested.owner_principal_id,
        idempotency_key=requested.idempotency_key,
        expected_revision=requested.revision,
        lease_token=requested.lease.token if requested.lease is not None else "missing",
        usage=ReadInvestigationRunUsage(tool_calls=0, execution_duration_ms=0),
        now=NOW,
    )
    blocker.set()
    for _ in range(10):
        await asyncio.sleep(0)
        if submission.task_id not in coordinator._active:
            break

    current = await run_store.get_by_task_id(task_id=submission.task_id)
    assert current == cancelled
    assert submission.task_id not in coordinator._active
