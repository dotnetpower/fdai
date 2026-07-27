"""Tests for the bounded common benchmark lifecycle."""

from __future__ import annotations

from collections import deque

import pytest

from fdai.benchmarking import (
    BenchmarkRunError,
    BenchmarkRunner,
    BenchmarkStatus,
    BenchmarkSubmission,
    BenchmarkTask,
)


def _task(task_id: str = "task-1") -> BenchmarkTask:
    return BenchmarkTask(
        run_id="run-1",
        task_id=task_id,
        stage="diagnosis",
        objective="Identify the failure.",
        target_ref="service/example",
    )


class _Adapter:
    adapter_id = "example"

    def __init__(self, tasks: tuple[BenchmarkTask, ...]) -> None:
        self.tasks = deque(tasks)
        self.submissions: list[BenchmarkSubmission] = []
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def next_task(self) -> BenchmarkTask | None:
        return self.tasks.popleft() if self.tasks else None

    async def submit(self, submission: BenchmarkSubmission) -> None:
        self.submissions.append(submission)

    async def close(self) -> None:
        self.closed = True


class _Processor:
    def __init__(self, *, task_id: str | None = None) -> None:
        self.task_id = task_id

    async def process(self, task: BenchmarkTask) -> BenchmarkSubmission:
        return BenchmarkSubmission(
            run_id=task.run_id,
            task_id=self.task_id or task.task_id,
            stage=task.stage,
            status=BenchmarkStatus.COMPLETED,
            summary="Evidence-backed result.",
            audit_ref="audit/example",
        )


class _StartFailingAdapter(_Adapter):
    async def start(self) -> None:
        raise RuntimeError("startup failed")


async def test_runner_processes_and_submits_each_task_once() -> None:
    adapter = _Adapter((_task("task-1"), _task("task-2")))

    summary = await BenchmarkRunner(adapter=adapter, processor=_Processor()).run()

    assert adapter.started is True
    assert adapter.closed is True
    assert [item.task_id for item in adapter.submissions] == ["task-1", "task-2"]
    assert summary.task_count == 2
    assert summary.completed_count == 2


async def test_runner_closes_adapter_when_start_fails() -> None:
    adapter = _StartFailingAdapter(())

    with pytest.raises(RuntimeError, match="startup failed"):
        await BenchmarkRunner(adapter=adapter, processor=_Processor()).run()

    assert adapter.closed is True


async def test_runner_rejects_duplicate_task_before_second_processing() -> None:
    task = _task()
    adapter = _Adapter((task, task))

    with pytest.raises(BenchmarkRunError, match="duplicate benchmark task"):
        await BenchmarkRunner(adapter=adapter, processor=_Processor()).run()

    assert adapter.closed is True
    assert len(adapter.submissions) == 1


async def test_runner_rejects_mismatched_submission_identity() -> None:
    adapter = _Adapter((_task(),))

    with pytest.raises(BenchmarkRunError, match="identity does not match"):
        await BenchmarkRunner(
            adapter=adapter,
            processor=_Processor(task_id="other-task"),
        ).run()

    assert adapter.submissions == []
    assert adapter.closed is True


async def test_runner_enforces_task_limit() -> None:
    adapter = _Adapter((_task("task-1"), _task("task-2")))

    with pytest.raises(BenchmarkRunError, match="task limit exceeded"):
        await BenchmarkRunner(adapter=adapter, processor=_Processor(), max_tasks=1).run()

    assert len(adapter.submissions) == 1
