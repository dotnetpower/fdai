"""Verifier adapter and shared complete-window self-health accounting."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from time import monotonic_ns
from uuid import uuid4

from fdai_service_contracts.self_health import SelfHealthSignalName

from fdai.core.quality_gate.gate import QualityCandidate, VerifierPolicy
from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VerifierObservationWindow:
    index: int
    completed: int
    rejected_or_abstained: int
    unknown: bool
    last_observed_at: datetime | None


class _RuntimeWindowedHealthSource:
    """Share complete-window mechanics without changing the producer's outcome meaning."""

    signal: SelfHealthSignalName
    _source_prefix = "runtime:t2-verifier"
    _diagnostic_prefix = "verifier_health"

    def __init__(
        self,
        *,
        metric: str,
        window_seconds: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        ticks: Callable[[], int] = monotonic_ns,
    ) -> None:
        if not 1 <= window_seconds <= 86_400:
            raise ValueError("health observation window must be in [1, 86400] seconds")
        self.metric = metric
        self.exporter_id = f"{self._source_prefix}:{uuid4().hex}"
        self._clock = clock
        self._ticks = ticks
        self._epoch = ticks()
        self._last_tick = self._epoch
        self._window_ticks = window_seconds * 1_000_000_000
        self._index = 0
        self._completed = 0
        self._rejected = 0
        self._unknown = False
        self._last_observed_at: datetime | None = None
        self._latest: VerifierObservationWindow | None = None
        self._bindings = 0
        self._pending = 0
        self._closed = False
        self._clock_broken = False

    def _bind(self) -> None:
        self._bindings += 1
        if self._bindings > 1:
            _LOGGER.error("%s_multiple_bindings", self._diagnostic_prefix)

    def close(self) -> None:
        self._closed = True
        self._latest = None

    @property
    def latest_window(self) -> VerifierObservationWindow | None:
        return self._latest

    def _advance(self) -> None:
        tick = self._ticks()
        if tick < self._last_tick:
            self._clock_broken = True
            self._latest = None
            _LOGGER.error("%s_monotonic_clock_regressed", self._diagnostic_prefix)
            return
        self._last_tick = tick
        index = (tick - self._epoch) // self._window_ticks
        if index == self._index:
            return
        self._latest = (
            VerifierObservationWindow(
                self._index,
                self._completed,
                self._rejected,
                self._unknown,
                self._last_observed_at,
            )
            if index == self._index + 1
            else None
        )
        self._index = index
        self._completed = 0
        self._rejected = 0
        self._unknown = False
        self._last_observed_at = None

    def _record(self, outcome: bool | None, *, known: bool) -> None:
        if self._closed:
            return
        try:
            self._advance()
            observed_at = self._clock()
        except (OSError, OverflowError) as exc:
            self._clock_broken = True
            _LOGGER.error(
                "%s_clock_unavailable", self._diagnostic_prefix, extra={"kind": type(exc).__name__}
            )
            return
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            self._clock_broken = True
            _LOGGER.error("%s_clock_not_aware", self._diagnostic_prefix)
            return
        self._completed += 1
        if not known or (outcome is not True and outcome is not False and outcome is not None):
            self._unknown = True
        elif outcome is not True:
            self._rejected += 1
        self._last_observed_at = observed_at.astimezone(UTC)

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        if self._closed or self._bindings == 0:
            raise SelfHealthExporterUnavailableError(reason="source_missing")
        if self._bindings != 1:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        if self._pending:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        try:
            self._advance()
        except (OSError, OverflowError) as exc:
            raise SelfHealthExporterUnavailableError(reason="source_unreachable") from exc
        if self._clock_broken:
            raise SelfHealthExporterUnavailableError(reason="source_malformed")
        window = self._latest
        if (
            window is None
            or self._unknown
            or window.completed == 0
            or window.unknown
            or window.last_observed_at is None
        ):
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        precision = max(64, 2 * len(str(window.completed)) + 32)
        with localcontext(Context(prec=precision)):
            rate = Decimal(window.rejected_or_abstained) / Decimal(window.completed)
        return SelfHealthExportSample(
            signal=self.signal,
            value=rate,
            observed_at=window.last_observed_at,
            source=self.exporter_id,
        )


class RuntimeVerifierHealthSource(_RuntimeWindowedHealthSource):
    """Observe the actual verifier through its unchanged synchronous policy contract."""

    signal = SelfHealthSignalName.VERIFIER_FAILURE_RATE

    def bind(self, verifier: VerifierPolicy) -> VerifierPolicy:
        self._bind()
        return _ObservedVerifier(verifier, self)


@dataclass(frozen=True, slots=True)
class _ObservedVerifier:
    delegate: VerifierPolicy
    source: RuntimeVerifierHealthSource

    def verify(self, candidate: QualityCandidate) -> bool | None:
        outcome: bool | None = None
        known = False
        try:
            outcome = self.delegate.verify(candidate)
            known = True
            return outcome
        finally:
            self.source._record(outcome, known=known)
