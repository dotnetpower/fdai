"""Process-owned periodic refresh lifecycle for local narrator timing pools."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol

_LOGGER = logging.getLogger(__name__)


class NarratorRefresher(Protocol):
    """Refresh and close one process-local narrator candidate pool."""

    async def refresh(self) -> None: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class PeriodicNarratorRefreshScheduler:
    """Run one immediate refresh and bounded non-overlapping periodic retries."""

    refresher: NarratorRefresher
    interval_seconds: float
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _stopped: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("narrator refresh interval MUST be positive")

    async def start(self) -> None:
        """Start one process-owned loop without waiting for its first provider call."""

        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="fdai-narrator-refresh")
        await asyncio.sleep(0)

    async def aclose(self) -> None:
        """Stop the loop and close any coalesced provider refresh owned by it."""

        self._stopped.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.refresher.aclose()

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.refresher.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate provider failures until next cycle
                _LOGGER.warning(
                    "narrator_periodic_refresh_failed",
                    extra={"error_type": type(exc).__name__},
                )
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self.interval_seconds,
                )
            except TimeoutError:
                continue


__all__ = ["NarratorRefresher", "PeriodicNarratorRefreshScheduler"]
