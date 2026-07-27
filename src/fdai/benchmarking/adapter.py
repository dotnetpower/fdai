"""External harness lifecycle contract for benchmark plugins."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fdai.benchmarking.contracts import BenchmarkSubmission, BenchmarkTask


class BenchmarkAdapterError(RuntimeError):
    """Normalized external benchmark transport or protocol failure."""


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """Translate one external benchmark harness into a task stream."""

    adapter_id: str

    async def start(self) -> None:
        """Validate prerequisites before any task is accepted."""
        ...

    async def next_task(self) -> BenchmarkTask | None:
        """Return the next task or ``None`` when the run is terminal."""
        ...

    async def submit(self, submission: BenchmarkSubmission) -> None:
        """Return one FDAI result to the external harness."""
        ...

    async def close(self) -> None:
        """Release transport resources without changing benchmark state."""
        ...


__all__ = ["BenchmarkAdapter", "BenchmarkAdapterError"]
