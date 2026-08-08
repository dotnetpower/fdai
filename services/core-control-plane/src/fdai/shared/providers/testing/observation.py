"""In-memory observation-depth fakes - Wave M1.5.

Four deterministic fakes that satisfy the Protocols in
:mod:`fdai.shared.providers.observation`. Each fake ships a
``seed_*`` method (test seeds), a ``next_error`` hook (one-shot error
injection for abstain-path tests), and captures every call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.shared.providers.observation import (
    DeploymentHistoryError,
    DeploymentHistoryProvider,
    DeploymentHistoryResult,
    DeploymentRecord,
    IncidentCorrelation,
    IncidentCorrelationError,
    IncidentCorrelator,
    LogQueryError,
    LogQueryProvider,
    LogQueryResult,
    MetricPoint,
    MetricQueryError,
    MetricQueryProvider,
    MetricQueryResult,
)


class InMemoryLogQueryProvider(LogQueryProvider):
    """Deterministic log query fake keyed by ``query``."""

    def __init__(self) -> None:
        self._seeds: dict[str, LogQueryResult] = {}
        self._next_error: LogQueryError | None = None
        self._calls: list[tuple[str, str, int]] = []

    def seed(self, query: str, result: LogQueryResult) -> None:
        self._seeds[query] = result

    def next_error(self, error: LogQueryError) -> None:
        self._next_error = error

    @property
    def calls(self) -> tuple[tuple[str, str, int], ...]:
        return tuple(self._calls)

    async def query_log(self, *, query: str, window: str, max_rows: int = 100) -> LogQueryResult:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err
        self._calls.append((query, window, max_rows))
        seeded = self._seeds.get(query)
        if seeded is not None:
            # Honour max_rows: clip if the seed exceeds it.
            if len(seeded.rows) > max_rows:
                return LogQueryResult(
                    rows=seeded.rows[:max_rows],
                    truncated=True,
                    scanned_records=seeded.scanned_records,
                    metadata=seeded.metadata,
                )
            return seeded
        return LogQueryResult(rows=(), truncated=False, scanned_records=0)


class InMemoryMetricQueryProvider(MetricQueryProvider):
    """Deterministic metric query fake keyed by ``(namespace, metric)``."""

    def __init__(self) -> None:
        self._seeds: dict[tuple[str, str], MetricQueryResult] = {}
        self._next_error: MetricQueryError | None = None
        self._calls: list[tuple[str, str, str, str]] = []

    def seed(
        self,
        *,
        namespace: str,
        metric: str,
        aggregation: str,
        points: tuple[MetricPoint, ...],
    ) -> None:
        self._seeds[(namespace, metric)] = MetricQueryResult(
            namespace=namespace,
            metric=metric,
            aggregation=aggregation,
            points=points,
        )

    def next_error(self, error: MetricQueryError) -> None:
        self._next_error = error

    @property
    def calls(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(self._calls)

    async def query_metric(
        self, *, namespace: str, metric: str, aggregation: str, window: str
    ) -> MetricQueryResult:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err
        self._calls.append((namespace, metric, aggregation, window))
        seeded = self._seeds.get((namespace, metric))
        if seeded is not None:
            return seeded
        return MetricQueryResult(
            namespace=namespace,
            metric=metric,
            aggregation=aggregation,
            points=(),
        )


class InMemoryDeploymentHistoryProvider(DeploymentHistoryProvider):
    """Deterministic deployment-history fake."""

    def __init__(self) -> None:
        self._records: list[DeploymentRecord] = []
        self._next_error: DeploymentHistoryError | None = None
        self._calls: list[tuple[str, str | None]] = []

    def seed(self, record: DeploymentRecord) -> None:
        self._records.append(record)

    def next_error(self, error: DeploymentHistoryError) -> None:
        self._next_error = error

    @property
    def calls(self) -> tuple[tuple[str, str | None], ...]:
        return tuple(self._calls)

    async def query_deployments(
        self, *, window: str, resource_ref: str | None = None
    ) -> DeploymentHistoryResult:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err
        self._calls.append((window, resource_ref))
        if resource_ref is None:
            filtered = tuple(self._records)
        else:
            filtered = tuple(r for r in self._records if resource_ref in r.resource_refs)
        return DeploymentHistoryResult(records=filtered, window=window)


class InMemoryIncidentCorrelator(IncidentCorrelator):
    """Deterministic incident correlator keyed by ``incident_id``.

    Unseeded ids raise :class:`IncidentCorrelationError` so tests
    exercise the abstain path explicitly.
    """

    def __init__(self) -> None:
        self._seeds: dict[str, IncidentCorrelation] = {}
        self._next_error: IncidentCorrelationError | None = None
        self._calls: list[str] = []

    def seed(self, correlation: IncidentCorrelation) -> None:
        self._seeds[correlation.incident_id] = correlation

    def next_error(self, error: IncidentCorrelationError) -> None:
        self._next_error = error

    @property
    def calls(self) -> tuple[str, ...]:
        return tuple(self._calls)

    async def correlate(self, *, incident_id: str) -> IncidentCorrelation:
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err
        self._calls.append(incident_id)
        seeded = self._seeds.get(incident_id)
        if seeded is not None:
            return seeded
        raise IncidentCorrelationError(f"no correlation seeded for {incident_id!r}")


def make_metric_point(timestamp: str, value: float) -> MetricPoint:
    """Convenience helper for tests that build MetricPoint tuples."""

    return MetricPoint(timestamp=timestamp, value=value)


def make_log_row(**fields: Any) -> Mapping[str, Any]:
    """Convenience helper - a log row is a plain mapping."""

    return dict(fields)


__all__ = [
    "InMemoryDeploymentHistoryProvider",
    "InMemoryIncidentCorrelator",
    "InMemoryLogQueryProvider",
    "InMemoryMetricQueryProvider",
    "make_log_row",
    "make_metric_point",
]
