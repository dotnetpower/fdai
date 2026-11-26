"""Receipt and aggregate persistence seam for programmatic pipelines."""

from __future__ import annotations

import asyncio
from typing import Protocol

from fdai.core.programmatic_pipeline.models import (
    ProgrammaticPipelineCallReceipt,
    ProgrammaticToolPipelineResult,
)


class ProgrammaticPipelineStore(Protocol):
    async def append_call(self, receipt: ProgrammaticPipelineCallReceipt) -> None: ...

    async def complete(
        self,
        *,
        idempotency_key: str,
        result: ProgrammaticToolPipelineResult,
    ) -> None: ...

    async def result_for(self, idempotency_key: str) -> ProgrammaticToolPipelineResult | None: ...

    async def calls_for(self, run_id: str) -> tuple[ProgrammaticPipelineCallReceipt, ...]: ...


class InMemoryProgrammaticPipelineStore:
    def __init__(self) -> None:
        self._calls: dict[str, list[ProgrammaticPipelineCallReceipt]] = {}
        self._results: dict[str, ProgrammaticToolPipelineResult] = {}
        self._lock = asyncio.Lock()

    async def append_call(self, receipt: ProgrammaticPipelineCallReceipt) -> None:
        async with self._lock:
            calls = self._calls.setdefault(receipt.run_id, [])
            if any(item.call_id == receipt.call_id for item in calls):
                raise ValueError("pipeline call receipt already exists")
            calls.append(receipt)

    async def complete(
        self,
        *,
        idempotency_key: str,
        result: ProgrammaticToolPipelineResult,
    ) -> None:
        async with self._lock:
            prior = self._results.get(idempotency_key)
            if prior is not None and prior != result:
                raise ValueError("pipeline idempotency key conflicts with another result")
            self._results[idempotency_key] = result

    async def result_for(self, idempotency_key: str) -> ProgrammaticToolPipelineResult | None:
        return self._results.get(idempotency_key)

    async def calls_for(self, run_id: str) -> tuple[ProgrammaticPipelineCallReceipt, ...]:
        return tuple(self._calls.get(run_id, ()))


__all__ = [
    "InMemoryProgrammaticPipelineStore",
    "ProgrammaticPipelineStore",
]
