"""Per-resource analyzers - the ``ResourceAnalyzer`` seam + threshold base.

Each analyzer inspects **one resource kind** (Application Gateway, MySQL,
Azure OpenAI, AKS, API Management, ...) over a time window and returns
:class:`AnalyzerFinding` observations. Analyzers are deterministic-first:
the reference :class:`ThresholdAnalyzer` reduces declared metrics to a
value and compares each against a bound; it never calls an LLM.

Metrics are read through the **shared** CSP-neutral
:class:`~fdai.shared.providers.metric.MetricProvider` seam - the same
streaming contract the anomaly detector and SLO evaluator use - so the
investigation analyzers run against the in-memory
:class:`~fdai.shared.providers.metric.StaticMetricProvider` in tests and
against the real Azure Monitor Logs / Datadog / Prometheus adapters under
``delivery/`` in production, with no parallel seam. Analyzers are read-only
and fail closed: a :class:`~fdai.shared.providers.metric.MetricProviderError`
propagates so the coordinator marks the run PARTIAL rather than fabricating
a healthy verdict.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.investigation.contract import AnalyzerFinding
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import MetricPoint, MetricProvider, MetricQuery

_DEFAULT_LABEL_KEY = "resource_id"


class Aggregation(StrEnum):
    """How a metric series is reduced to a single comparable value."""

    MAX = "max"
    MIN = "min"
    AVG = "avg"
    SUM = "sum"
    LAST = "last"


def reduce_values(values: Sequence[float], how: Aggregation) -> float | None:
    """Reduce ``values`` to one float; ``None`` when the series is empty."""
    if not values:
        return None
    if how is Aggregation.MAX:
        return max(values)
    if how is Aggregation.MIN:
        return min(values)
    if how is Aggregation.SUM:
        return sum(values)
    if how is Aggregation.AVG:
        return sum(values) / len(values)
    return values[-1]  # LAST


@runtime_checkable
class ResourceAnalyzer(Protocol):
    """Analyze one resource kind and emit findings."""

    @property
    def resource_kind(self) -> str:
        """The single resource kind this analyzer understands."""
        ...

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        """Return findings for ``resource_ref`` (empty when healthy)."""
        ...


class Comparison(StrEnum):
    """How a threshold compares an observed value to its bound."""

    GTE = "gte"
    LTE = "lte"


@dataclass(frozen=True, slots=True)
class Threshold:
    """One deterministic metric threshold.

    Fires a finding when ``metric`` (reduced by ``aggregation`` over the
    window) breaches ``bound`` in the ``compare`` direction.
    ``remediation_ref`` names the ActionType the breach implies (if any) -
    the finding proposes, the risk gate decides.
    """

    metric: str
    compare: Comparison
    bound: float
    severity: Severity
    signal: str
    observation: str
    aggregation: Aggregation = Aggregation.MAX
    remediation_ref: str | None = None

    def breached(self, value: float) -> bool:
        """True iff ``value`` breaches this threshold."""
        if self.compare is Comparison.GTE:
            return value >= self.bound
        return value <= self.bound


class ThresholdAnalyzer:
    """Reference analyzer: reduce shared-seam metrics and compare thresholds.

    Deterministic and network-free given a
    :class:`~fdai.shared.providers.metric.StaticMetricProvider`. A fork can
    register richer analyzers for the same kind by binding a different
    :class:`ResourceAnalyzer`; this one covers the demo's metric-threshold
    cases. ``label_key`` is the label a series carries the resource id under
    (``resource_id`` by default), matching the ``MetricQuery.labels``
    contract.
    """

    __slots__ = ("_kind", "_label_key", "_provider", "_thresholds", "_wall_clock")

    def __init__(
        self,
        *,
        resource_kind: str,
        provider: MetricProvider,
        thresholds: Sequence[Threshold],
        label_key: str = _DEFAULT_LABEL_KEY,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not resource_kind:
            raise ValueError("ThresholdAnalyzer.resource_kind MUST be non-empty")
        self._kind = resource_kind
        self._provider = provider
        self._thresholds = tuple(thresholds)
        self._label_key = label_key
        self._wall_clock: Callable[[], datetime] = wall_clock or (lambda: datetime.now(tz=UTC))

    @property
    def resource_kind(self) -> str:
        return self._kind

    async def analyze(
        self, *, resource_ref: str, window_seconds: float
    ) -> Sequence[AnalyzerFinding]:
        until = self._wall_clock()
        since = until - timedelta(seconds=window_seconds)
        findings: list[AnalyzerFinding] = []
        for threshold in self._thresholds:
            points = await self._gather(
                metric=threshold.metric,
                resource_ref=resource_ref,
                since=since,
                until=until,
                aggregation=threshold.aggregation,
            )
            if not points:
                continue
            value = reduce_values([p.value for p in points], threshold.aggregation)
            if value is None or not threshold.breached(value):
                continue
            occurred_at = max(p.at for p in points)
            findings.append(
                AnalyzerFinding(
                    resource_ref=resource_ref,
                    resource_kind=self._kind,
                    signal=threshold.signal,
                    observation=threshold.observation,
                    severity=threshold.severity,
                    occurred_at=occurred_at,
                    evidence_refs=(f"{threshold.metric}={value:g}",),
                    remediation_ref=threshold.remediation_ref,
                )
            )
        return tuple(findings)

    async def _gather(
        self,
        *,
        metric: str,
        resource_ref: str,
        since: datetime,
        until: datetime,
        aggregation: Aggregation,
    ) -> list[MetricPoint]:
        query = MetricQuery(
            metric_name=metric,
            labels={self._label_key: resource_ref},
            since=since,
            until=until,
            aggregation=aggregation.value,
        )
        return [point async for point in self._provider.query(query)]


__all__ = [
    "Aggregation",
    "Comparison",
    "MetricProvider",
    "ResourceAnalyzer",
    "Threshold",
    "ThresholdAnalyzer",
    "reduce_values",
]
