"""Process- and binding-qualified observations of normal embedding provider calls."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from threading import Lock
from uuid import uuid4

import httpx
from fdai_service_contracts.self_health import SelfHealthSignalName

from fdai.shared.providers.self_health import (
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)


@dataclass(slots=True)
class ProviderInvocationObservation:
    result: bool | None = None


class EmbeddingProviderObservations:
    """Retain one fully settled invocation cohort, never a rate or all-model health."""

    def __init__(
        self,
        *,
        binding_digest: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.exporter_id = (
            f"process:provider:t1.embedding:{uuid4().hex}:{binding_digest.removeprefix('sha256:')}"
        )
        self._clock = clock
        self._lock = Lock()
        self._pending: set[object] = set()
        self._last: tuple[bool, datetime] | None = None
        self._missing_reason = "source_missing"
        self._cohort_result: bool | None = True

    @contextmanager
    def invocation(self) -> Iterator[ProviderInvocationObservation]:
        """Observe one logical call; unresolved or cancelled work never becomes success."""
        token = object()
        observation = ProviderInvocationObservation()
        with self._lock:
            if not self._pending:
                self._cohort_result = True
            self._pending.add(token)
        try:
            yield observation
        finally:
            with self._lock:
                recorded_at = self._clock()
                self._pending.remove(token)
                if observation.result is None:
                    self._cohort_result = None
                elif self._cohort_result is not None:
                    self._cohort_result = self._cohort_result and observation.result
                if not self._pending:
                    self._last = (
                        (self._cohort_result, recorded_at)
                        if self._cohort_result is not None
                        else None
                    )
                    self._missing_reason = "source_incomplete"

    def snapshot(self) -> tuple[bool, datetime]:
        with self._lock:
            if self._pending:
                raise SelfHealthExporterUnavailableError(reason="source_incomplete")
            if self._last is None:
                raise SelfHealthExporterUnavailableError(reason=self._missing_reason)
            return self._last


@dataclass(frozen=True, slots=True)
class EmbeddingProviderHealthExporter:
    observations: EmbeddingProviderObservations
    client: httpx.AsyncClient
    maximum_age_seconds: int
    signal: SelfHealthSignalName = SelfHealthSignalName.ADAPTER_HEALTHCHECK
    metric: str = "fdai.adapter.healthy"

    @property
    def exporter_id(self) -> str:
        return self.observations.exporter_id

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        if self.client.is_closed:
            raise SelfHealthExporterUnavailableError(reason="source_unreachable")
        success, observed_at = self.observations.snapshot()
        age = (now - observed_at).total_seconds()
        if age < 0:
            raise SelfHealthExporterUnavailableError(reason="source_from_future")
        if age > self.maximum_age_seconds:
            raise SelfHealthExporterUnavailableError(reason="source_stale")
        return SelfHealthExportSample(
            signal=self.signal,
            value=Decimal(int(success)),
            observed_at=observed_at,
            source=self.exporter_id,
        )
