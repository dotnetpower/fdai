"""Actual process-owned ingest-to-first-tier-decision observations."""

from __future__ import annotations

import hashlib
import logging
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic_ns
from uuid import uuid4

from fdai_service_contracts.self_health import SelfHealthSignalName

from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)
from fdai.shared.providers.stage_publisher import (
    ObservationSource,
    StageEvent,
    StageName,
    StagePhase,
    StagePublisher,
)

_LOGGER = logging.getLogger(__name__)
_SECOND = 1_000_000_000


class RuntimeEventLagSource:
    """Keep in-flight ages visible and fail explicitly when the observed set is incomplete."""

    signal = SelfHealthSignalName.EVENT_LAG

    def __init__(
        self,
        *,
        metric: str,
        maximum_age_seconds: int,
        capacity: int = 4096,
        ticks: Callable[[], int] = monotonic_ns,
    ) -> None:
        if not 1 <= maximum_age_seconds <= 86_400 or not 1 <= capacity <= 100_000:
            raise ValueError("event lag observation bounds are invalid")
        self.metric = metric
        self.exporter_id = "runtime:first-tier-decision:" + uuid4().hex
        self._age = maximum_age_seconds * _SECOND
        self._capacity = capacity
        self._ticks = ticks
        self._last_tick = ticks()
        self._pending: dict[bytes, int] = {}
        self._finished: dict[bytes, int] = {}
        self._recent: deque[tuple[int, bytes, int]] = deque()
        self._canaries: set[bytes] = set()
        self._unknown_at: int | None = None
        self._bindings = 0
        self._closed = False
        self._broken = False
        self._ever_completed = False

    def wrap(self, publisher: StagePublisher) -> ObservedDecisionStagePublisher:
        self._bindings += 1
        return ObservedDecisionStagePublisher(publisher, self)

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
        self._finished.clear()
        self._recent.clear()
        self._canaries.clear()

    def _advance(self) -> int:
        tick = self._ticks()
        if tick < self._last_tick:
            self._broken = True
            _LOGGER.error("event_lag_clock_regressed")
        self._last_tick = tick
        while self._recent and tick - self._recent[0][0] > self._age:
            _, key, _ = self._recent.popleft()
            del self._finished[key]
        return tick

    @staticmethod
    def _key(event: StageEvent) -> bytes:
        return hashlib.sha256(
            (event.event_id + "\0" + event.correlation_id).encode("utf-8")
        ).digest()

    def record(self, event: StageEvent) -> None:
        if self._closed:
            return
        tick = self._advance()
        if event.source is not ObservationSource.RUNTIME_OBSERVED:
            self._unknown_at = tick
            _LOGGER.warning("event_lag_untrusted_observation")
            return
        key = self._key(event)
        if key in self._canaries:
            if event.stage is StageName.AUDIT and event.phase is StagePhase.DONE:
                self._canaries.remove(key)
            return
        if event.stage is StageName.INGEST and event.phase is StagePhase.DONE:
            if event.detail.get("event_type") == "fdai.control.canary":
                if len(self._canaries) >= self._capacity:
                    self._overflow()
                else:
                    self._canaries.add(key)
                return
            if key in self._pending or key in self._finished:
                return
            if len(self._pending) >= self._capacity:
                self._overflow()
                return
            self._pending[key] = tick
        elif (
            event.stage is StageName.VERIFY
            and event.phase is StagePhase.DONE
            and isinstance(event.detail.get("tier"), str)
            and event.detail.get("tier") in {"t0", "t1", "t2"}
        ):
            if key in self._finished:
                return
            started = self._pending.pop(key, None)
            if started is None:
                self._unknown_at = tick
                _LOGGER.warning("event_lag_ingress_unobserved")
                return
            if len(self._recent) >= self._capacity:
                self._overflow()
                return
            self._finished[key] = tick
            self._recent.append((tick, key, tick - started))
            self._ever_completed = True
        elif event.phase is StagePhase.FAILED or (
            event.stage is StageName.AUDIT and event.phase is StagePhase.DONE
        ):
            if key in self._pending:
                del self._pending[key]
                self._unknown_at = tick
                _LOGGER.warning("event_lag_terminal_without_tier_decision")

    def _overflow(self) -> None:
        self._broken = True
        _LOGGER.error("event_lag_observation_capacity_exceeded")

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        if now.utcoffset() is None:
            raise ValueError("event lag observation requires an aware timestamp")
        tick = self._advance()
        if self._closed or self._bindings != 1 or self._broken:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        if self._unknown_at is not None and tick - self._unknown_at <= self._age:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        ages = [tick - began for began in self._pending.values()]
        ages.extend(value for _, _, value in self._recent)
        if not ages:
            raise SelfHealthExporterUnavailableError(
                reason="source_stale" if self._ever_completed else "source_missing"
            )
        elapsed = max(ages)
        return SelfHealthExportSample(
            signal=self.signal,
            value=Decimal(f"{elapsed // _SECOND}.{elapsed % _SECOND:09d}"),
            observed_at=now.astimezone(UTC),
            source=self.exporter_id,
        )


class ObservedDecisionStagePublisher:
    """Observe trusted local stages before preserving the original publisher call."""

    def __init__(self, publisher: StagePublisher, source: RuntimeEventLagSource) -> None:
        self._publisher = publisher
        self._source = source

    async def emit(self, event: StageEvent) -> None:
        self._source.record(event)
        await self._publisher.emit(event)
