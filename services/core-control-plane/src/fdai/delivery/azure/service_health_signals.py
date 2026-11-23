"""Detect active Azure Service Health events and record them as report signals.

Read-only and no-authority: the job reads one server-owned subscription through
the reviewed Service Health reader and writes idempotent report-feed signals.
It never triggers an action.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from fdai.core.ontology_platform.service_health_queries import ServiceHealthReader
from fdai.core.report_feed.adapters import signals_from_service_health
from fdai.core.report_feed.models import ReportSignal

_LOGGER = logging.getLogger("fdai.service_health_signals")
_MIN_INTERVAL_SECONDS: Final = 60.0
_MAX_BACKOFF_SECONDS: Final = 900.0


class ServiceHealthSignalWriter(Protocol):
    async def record_many(self, signals: Sequence[ReportSignal]) -> None: ...


@dataclass(frozen=True, slots=True)
class ServiceHealthSignalOutcome:
    """One detection pass; an incomplete pass is never evidence of a clear subscription."""

    observed: int
    recorded: int
    complete: bool
    limitation: str | None


class ServiceHealthSignalJob:
    """Poll active events and record signals; the store deduplicates by signal id."""

    def __init__(
        self,
        *,
        reader: ServiceHealthReader,
        writer: ServiceHealthSignalWriter,
        interval_seconds: float = 300.0,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not (
            math.isfinite(interval_seconds) and _MIN_INTERVAL_SECONDS <= interval_seconds <= 3600
        ):
            raise ValueError(
                f"interval_seconds MUST be finite in [{_MIN_INTERVAL_SECONDS:g}, 3600]"
            )
        if not (math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 300):
            raise ValueError("timeout_seconds MUST be finite in (0, 300]")
        self._reader: Final = reader
        self._writer: Final = writer
        self._interval: Final = interval_seconds
        self._timeout: Final = timeout_seconds

    async def run_once(self) -> ServiceHealthSignalOutcome:
        collection = await self._reader.read_active()
        signals = signals_from_service_health(collection)
        await self._writer.record_many(signals)
        return ServiceHealthSignalOutcome(
            observed=len(collection.observations),
            recorded=len(signals),
            complete=collection.complete,
            limitation=collection.limitation,
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until stopped; a failed pass backs off and never ends the loop."""

        failures = 0
        while not stop.is_set():
            delay = self._interval
            try:
                outcome = await asyncio.wait_for(self.run_once(), timeout=self._timeout)
            except Exception as exc:  # noqa: BLE001 - one bad pass must not stop detection
                failures += 1
                delay = min(self._interval * 2**failures, _MAX_BACKOFF_SECONDS)
                _LOGGER.warning("service health detection failed: %s", type(exc).__name__)
            else:
                failures = 0
                if not outcome.complete:
                    _LOGGER.warning("service health detection incomplete: %s", outcome.limitation)
            await self._wait(stop, delay)

    async def _wait(self, stop: asyncio.Event, delay: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            return


__all__ = ["ServiceHealthSignalJob", "ServiceHealthSignalOutcome", "ServiceHealthSignalWriter"]
