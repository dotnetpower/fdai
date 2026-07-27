"""Bounded benchmark lifecycle runner with an FDAI-owned task processor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.benchmarking.adapter import BenchmarkAdapter
from fdai.benchmarking.contracts import BenchmarkStatus, BenchmarkSubmission, BenchmarkTask


class BenchmarkRunError(RuntimeError):
    """Benchmark lifecycle stopped before a trustworthy result was submitted."""


@runtime_checkable
class BenchmarkTaskProcessor(Protocol):
    """Process benchmark tasks through the FDAI event and audit path."""

    async def process(self, task: BenchmarkTask) -> BenchmarkSubmission: ...


@dataclass(frozen=True, slots=True)
class BenchmarkRunSummary:
    """Bounded terminal counts for one adapter run."""

    adapter_id: str
    task_count: int
    completed_count: int
    held_count: int
    failed_count: int


class BenchmarkRunner:
    """Drive an external task stream without owning any FDAI decision."""

    def __init__(
        self,
        *,
        adapter: BenchmarkAdapter,
        processor: BenchmarkTaskProcessor,
        max_tasks: int = 1_000,
    ) -> None:
        if not isinstance(adapter, BenchmarkAdapter):
            raise TypeError("adapter MUST implement BenchmarkAdapter")
        if not isinstance(processor, BenchmarkTaskProcessor):
            raise TypeError("processor MUST implement BenchmarkTaskProcessor")
        if max_tasks < 1:
            raise ValueError("max_tasks MUST be >= 1")
        self._adapter = adapter
        self._processor = processor
        self._max_tasks = max_tasks

    async def run(self) -> BenchmarkRunSummary:
        """Process each unique task once and submit only correlated results."""

        seen: set[tuple[str, str, str]] = set()
        counts = {status: 0 for status in BenchmarkStatus}
        try:
            await self._adapter.start()
            while True:
                task = await self._adapter.next_task()
                if task is None:
                    break
                identity = (task.run_id, task.task_id, task.stage)
                if identity in seen:
                    raise BenchmarkRunError(f"duplicate benchmark task identity: {identity!r}")
                if len(seen) >= self._max_tasks:
                    raise BenchmarkRunError(f"benchmark task limit exceeded ({self._max_tasks})")
                seen.add(identity)

                submission = await self._processor.process(task)
                if (submission.run_id, submission.task_id, submission.stage) != identity:
                    raise BenchmarkRunError(
                        "processor submission identity does not match the benchmark task"
                    )
                await self._adapter.submit(submission)
                counts[submission.status] += 1
        finally:
            await self._adapter.close()

        return BenchmarkRunSummary(
            adapter_id=self._adapter.adapter_id,
            task_count=len(seen),
            completed_count=counts[BenchmarkStatus.COMPLETED],
            held_count=counts[BenchmarkStatus.HELD],
            failed_count=counts[BenchmarkStatus.FAILED],
        )


__all__ = [
    "BenchmarkRunError",
    "BenchmarkRunner",
    "BenchmarkRunSummary",
    "BenchmarkTaskProcessor",
]
