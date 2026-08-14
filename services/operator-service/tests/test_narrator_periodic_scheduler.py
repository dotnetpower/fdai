"""Focused lifecycle tests for periodic narrator timing refresh."""

from __future__ import annotations

import asyncio

import pytest
from fdai_operator_service.adapters.narrator_periodic_scheduler import (
    PeriodicNarratorRefreshScheduler,
)


class _Refresher:
    def __init__(self, *, fail_first: bool = False, block: bool = False) -> None:
        self.calls = 0
        self.closed = 0
        self.cancelled = asyncio.Event()
        self.reached_two = asyncio.Event()
        self.started = asyncio.Event()
        self._fail_first = fail_first
        self._block = block
        self._release = asyncio.Event()

    async def refresh(self) -> None:
        self.calls += 1
        self.started.set()
        if self._fail_first and self.calls == 1:
            raise RuntimeError("bounded provider failure")
        if self.calls >= 2:
            self.reached_two.set()
        if self._block:
            try:
                await self._release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def aclose(self) -> None:
        self.closed += 1
        self._release.set()


async def test_periodic_refresh_runs_immediately_then_after_interval() -> None:
    refresher = _Refresher()
    scheduler = PeriodicNarratorRefreshScheduler(refresher, interval_seconds=0.001)

    await scheduler.start()
    await asyncio.wait_for(refresher.reached_two.wait(), timeout=1)
    await scheduler.aclose()

    assert refresher.calls >= 2
    assert refresher.closed == 1


async def test_periodic_refresh_isolates_failure_and_retries() -> None:
    refresher = _Refresher(fail_first=True)
    scheduler = PeriodicNarratorRefreshScheduler(refresher, interval_seconds=0.001)

    await scheduler.start()
    await asyncio.wait_for(refresher.reached_two.wait(), timeout=1)
    await scheduler.aclose()

    assert refresher.calls >= 2


async def test_periodic_refresh_coalesces_start_and_cancels_inflight() -> None:
    refresher = _Refresher(block=True)
    scheduler = PeriodicNarratorRefreshScheduler(refresher, interval_seconds=60)

    await asyncio.gather(scheduler.start(), scheduler.start())
    await asyncio.wait_for(refresher.started.wait(), timeout=1)
    assert refresher.calls == 1

    await scheduler.aclose()

    assert refresher.cancelled.is_set()
    assert refresher.closed == 1


def test_periodic_refresh_requires_positive_interval() -> None:
    with pytest.raises(ValueError, match="interval MUST be positive"):
        PeriodicNarratorRefreshScheduler(_Refresher(), interval_seconds=0)
