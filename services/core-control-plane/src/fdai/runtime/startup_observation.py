"""One process-owned runtime-entry to first guarded-ready observation."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fdai_service_contracts.self_health import SelfHealthSignalName

from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)


class RuntimeStartupDurationSource:
    """Measure one actual startup, never a fleet rate or a synthetic warm-up."""

    signal = SelfHealthSignalName.COLD_START_DURATION
    metric = "fdai.runtime.cold_start_duration_seconds"

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._started = monotonic()
        self._readiness: Callable[[], bool] | None = None
        self._sample: SelfHealthExportSample | None = None
        self._closed = False
        self.exporter_id = f"runtime:entry-to-first-guarded-ready:{uuid4().hex}"

    def bind_readiness(self, readiness: Callable[[], bool]) -> None:
        """Start observing only after the actual runtime composition is complete."""
        self._readiness = readiness
        self.is_ready()

    def is_ready(self) -> bool:
        """Observe the unchanged readiness guard without raising its authority."""
        ready = not self._closed and self._readiness is not None and self._readiness()
        if ready:
            self._record_first_ready(self._utc_now())
        return ready

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        if self._closed or self._readiness is None:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        if self._sample is None and self._readiness():
            self._record_first_ready(now)
        if self._sample is None:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        return self._sample

    def close(self) -> None:
        self._closed = True
        self._readiness = None

    def _record_first_ready(self, observed_at: datetime) -> None:
        if self._sample is None:
            self._sample = SelfHealthExportSample(
                signal=self.signal,
                value=Decimal(str(self._monotonic() - self._started)),
                observed_at=observed_at,
                source=self.exporter_id,
            )
