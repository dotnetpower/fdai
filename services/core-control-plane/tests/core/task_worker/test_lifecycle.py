"""Admission, cancellation and recovery must not race an active worker."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.task_worker import (
    InMemoryTaskWorkerStore,
    TaskWorkerBudget,
    TaskWorkerOutput,
    TaskWorkerRequest,
    TaskWorkerRuntime,
    TaskWorkerRuntimeConfig,
    TaskWorkerStatus,
    TaskWorkerUsage,
)


def _request(worker_id: str = "worker:one") -> TaskWorkerRequest:
    return TaskWorkerRequest(
        worker_id=worker_id,
        parent_trace_ref="trace:one",
        cancellation_owner="person:one",
        goal="Read bounded evidence.",
        evidence_refs=(),
        constraints=(),
        requested_tools=frozenset(),
        budget=TaskWorkerBudget(),
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )


class _Executor:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def execute(self, **kwargs: object) -> TaskWorkerOutput:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return TaskWorkerOutput("No evidence.", (), (), TaskWorkerUsage(), abstained=True)


async def test_concurrent_duplicate_admission_joins_the_original_task() -> None:
    entered, release, retry_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Store(InMemoryTaskWorkerStore):
        async def append_event(self, *args, **kwargs):
            if kwargs["kind"] == "worker.created":
                entered.set()
                await release.wait()
            return await super().append_event(*args, **kwargs)

    executor = _Executor()
    runtime = TaskWorkerRuntime(store=Store(), executor=executor, tools=())
    first = asyncio.create_task(runtime.start(_request(), parent_visible_tools=frozenset()))
    await entered.wait()

    async def retry():
        retry_entered.set()
        return await runtime.start(_request(), parent_visible_tools=frozenset())

    second = asyncio.create_task(retry())
    await retry_entered.wait()
    release.set()
    try:
        original, repeated = await asyncio.gather(first, second)
        assert original is repeated
        executor.release.set()
        assert (await original).status is TaskWorkerStatus.ABSTAINED
        assert executor.calls == 1
    finally:
        await runtime.aclose()


async def test_restart_recovery_cannot_terminalize_its_own_live_work() -> None:
    store, executor = InMemoryTaskWorkerStore(), _Executor()
    runtime = TaskWorkerRuntime(store=store, executor=executor, tools=())
    task = await runtime.start(_request(), parent_visible_tools=frozenset())
    await executor.entered.wait()
    try:
        with pytest.raises(RuntimeError, match="active"):
            await runtime.recover_interrupted()
        assert (await store.get("worker:one")).status is TaskWorkerStatus.RUNNING
    finally:
        executor.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.aclose()


async def test_queued_owner_cancellation_has_a_durable_terminal_result() -> None:
    store, executor = InMemoryTaskWorkerStore(), _Executor()
    runtime = TaskWorkerRuntime(
        store=store,
        executor=executor,
        tools=(),
        config=TaskWorkerRuntimeConfig(max_parallelism=1),
    )
    first = await runtime.start(_request(), parent_visible_tools=frozenset())
    await executor.entered.wait()
    queued_request = replace(_request(), worker_id="worker:queued")
    queued = await runtime.start(queued_request, parent_visible_tools=frozenset())
    try:
        await runtime.cancel("worker:queued", owner="person:one")
        result = await queued
        assert result.status is TaskWorkerStatus.CANCELLED
        assert (await store.get("worker:queued")).result == result
        assert executor.calls == 1
    finally:
        executor.release.set()
        await first
        await runtime.aclose()
