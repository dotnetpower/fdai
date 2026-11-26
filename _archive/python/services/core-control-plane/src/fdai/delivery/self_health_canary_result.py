"""Coherent numeric result and sanitized state for a witnessed scheduled execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.self_health import (
    OperationalStateFieldName,
    OperationalStateFieldStatus,
    OperationalStateFieldV1,
    SelfHealthSignalName,
)
from psycopg import Error as DatabaseError

from fdai.delivery.canary_sequence import CanaryConsumption, consumed_canary_sequence
from fdai.delivery.kubernetes_canary import AksScheduledCanaryObserver
from fdai.shared.providers.self_health import (
    OperationalStateFieldExporter,
    SelfHealthExporter,
    SelfHealthExporterUnavailableError,
    SelfHealthExportSample,
)
from fdai.shared.providers.state_store import StateStore


@runtime_checkable
class _CanarySequenceReader(Protocol):
    async def read_consumed_canary_sequence(
        self, *, slot: str
    ) -> tuple[tuple[Mapping[str, Any], ...], bool]: ...


@dataclass(frozen=True, slots=True)
class _Observation:
    consumption: CanaryConsumption
    state_digest: str


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class ScheduledCanarySource:
    store: StateStore
    observer: AksScheduledCanaryObserver
    clock: Callable[[], datetime] = _now
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _at: datetime | None = field(default=None, init=False, repr=False)
    _result: _Observation | str = field(default="source_incomplete", init=False, repr=False)
    _consumers: set[str] = field(default_factory=set, init=False, repr=False)

    async def observe(
        self, *, now: datetime, consumer: Literal["result", "state", "direct"] = "direct"
    ) -> _Observation:
        if now.utcoffset() is None:
            raise ValueError("canary source observation requires an aware timestamp")
        async with self._lock:
            if self._at is not None and now < self._at:
                raise SelfHealthExporterUnavailableError(reason="source_malformed")
            if self._at != now:
                self._at, self._result = now, "source_incomplete"
                self._consumers.clear()
                try:
                    self._result = await self._collect(now=now)
                except SelfHealthExporterUnavailableError as exc:
                    self._result = exc.reason
                except (OSError, DatabaseError) as exc:
                    self._result = "source_unreachable"
                    raise SelfHealthExporterUnavailableError(reason="source_unreachable") from exc
            elif consumer in self._consumers and isinstance(self._result, _Observation):
                self._result = "source_incomplete"
            self._consumers.add(consumer)
            if isinstance(self._result, str):
                raise SelfHealthExporterUnavailableError(reason=self._result)
            return self._result

    async def _collect(self, *, now: datetime) -> _Observation:
        if not isinstance(self.store, _CanarySequenceReader):
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        first = await self.observer.observe(now=now)
        rows, truncated = await self.store.read_consumed_canary_sequence(slot=first.slot)
        consumption = consumed_canary_sequence(rows, slot=first.slot, truncated=truncated, now=now)
        completed_at = self.clock()
        if completed_at.utcoffset() is None or completed_at < now:
            raise SelfHealthExporterUnavailableError(reason="source_malformed")
        second = await self.observer.observe(now=completed_at)
        if first != second:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        final_at = self.clock()
        if final_at.utcoffset() is None or final_at < completed_at:
            raise SelfHealthExporterUnavailableError(reason="source_malformed")
        if final_at >= second.valid_until:
            raise SelfHealthExporterUnavailableError(reason="source_incomplete")
        if consumption.observed_at < first.scheduled_at:
            raise SelfHealthExporterUnavailableError(reason="source_malformed")
        return _Observation(
            consumption=consumption,
            state_digest=canonical_digest(
                {
                    "scheduler": first.binding_digest,
                    "sequence": consumption.sequence_digest,
                    "outcome": consumption.outcome,
                    "observed_at": consumption.observed_at.isoformat(),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ScheduledCanaryResultExporter:
    source: ScheduledCanarySource
    metric: str
    signal: SelfHealthSignalName = SelfHealthSignalName.CANARY_RESULT
    exporter_id: str = "native:aks-canary:consumed-result"

    async def observe(self, *, now: datetime) -> SelfHealthExportSample:
        observation = await self.source.observe(now=now, consumer="result")
        return SelfHealthExportSample(
            signal=self.signal,
            value=observation.consumption.value,
            observed_at=observation.consumption.observed_at,
            source=self.exporter_id,
        )


@dataclass(frozen=True, slots=True)
class ScheduledCanaryStateExporter:
    source: ScheduledCanarySource
    maximum_age_seconds: int
    field_name: OperationalStateFieldName = OperationalStateFieldName.CANARY
    exporter_id: str = "native:aks-canary:consumed-state"

    async def observe(self, *, now: datetime) -> OperationalStateFieldV1:
        observation = await self.source.observe(now=now, consumer="state")
        if observation.consumption.outcome == "cancelled":
            return OperationalStateFieldV1(
                name=self.field_name,
                status=OperationalStateFieldStatus.UNAVAILABLE,
                source=self.exporter_id,
                maximum_age_seconds=self.maximum_age_seconds,
                fresh=False,
                reason="canary_cancelled",
            )
        observed_at = observation.consumption.observed_at
        fresh = 0 <= (now - observed_at).total_seconds() <= self.maximum_age_seconds
        return OperationalStateFieldV1(
            name=self.field_name,
            status=OperationalStateFieldStatus.AVAILABLE,
            value_digest=observation.state_digest,
            source=self.exporter_id,
            observed_at=observed_at,
            maximum_age_seconds=self.maximum_age_seconds,
            fresh=fresh,
            reason=f"canary_{observation.consumption.outcome}" if fresh else "source_stale",
        )


def runtime_canary_exporters(
    *,
    store: StateStore,
    environment: Mapping[str, str],
    metric: str,
    maximum_age_seconds: int,
) -> tuple[SelfHealthExporter, OperationalStateFieldExporter] | None:
    namespace = environment.get("FDAI_CANARY_OBSERVER_NAMESPACE", "")
    cronjob = environment.get("FDAI_CANARY_OBSERVER_CRONJOB", "")
    if not namespace and not cronjob:
        return None
    if not namespace or not cronjob:
        raise ValueError("canary observer namespace and CronJob must be configured together")
    source = ScheduledCanarySource(
        store=store, observer=AksScheduledCanaryObserver(namespace=namespace, cronjob=cronjob)
    )
    return (
        ScheduledCanaryResultExporter(source, metric),
        ScheduledCanaryStateExporter(source, maximum_age_seconds),
    )
