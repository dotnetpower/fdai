"""Compose bounded semantic metrics with workload and SLO evidence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from fdai.shared.providers.metric import (
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceMetric,
    AksCommerceSlo,
    AksCommerceWorkload,
)

from fdai_aks_commerce.models import AksCommerceEvidenceFrame


@dataclass(frozen=True, slots=True)
class CommerceMetricBinding:
    """One semantic metric, exact target, and bounded reduction."""

    name: str
    resource_ref: str
    unit: str
    reduction: str
    source_ref: str
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.reduction not in {"last", "sum"}:
            raise ValueError("AKS commerce metric reduction must be last or sum")
        if not self.name or not self.resource_ref or not self.source_ref:
            raise ValueError("AKS commerce metric binding identity must be non-empty")


@dataclass(frozen=True, slots=True)
class WorkloadEvidenceSet:
    """Exact resource and change evidence supplied by the AKS read plane."""

    workloads: tuple[AksCommerceWorkload, ...]
    evidence_refs: tuple[str, ...]
    gaps: tuple[str, ...] = ()
    deployment_changed: bool = False
    rollout_stalled: bool = False


class CommerceWorkloadEvidenceReader(Protocol):
    """Read one exact business-service workload path."""

    async def read(self, service_id: str, *, cutoff: datetime) -> WorkloadEvidenceSet: ...


class CommerceSloEvidenceReader(Protocol):
    """Read workload SLO evaluations for one exact window."""

    async def read(
        self,
        service_id: str,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[AksCommerceSlo, ...]: ...


class MetricCommerceObservationSource:
    """Build a complete frame from provider metrics and injected read-plane evidence."""

    def __init__(
        self,
        *,
        metric_provider: MetricProvider,
        metric_bindings: Sequence[CommerceMetricBinding],
        workload_reader: CommerceWorkloadEvidenceReader,
        slo_reader: CommerceSloEvidenceReader,
        dependency_paths: dict[str, tuple[str, ...]],
        window: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not timedelta(seconds=1) <= window <= timedelta(hours=24):
            raise ValueError("AKS commerce observation window must be in [1 second, 24 hours]")
        if not metric_bindings or len(metric_bindings) > 32:
            raise ValueError("AKS commerce metric bindings must contain 1 to 32 items")
        names = [binding.name for binding in metric_bindings]
        if len(names) != len(set(names)):
            raise ValueError("AKS commerce metric binding names must be unique")
        self._metric_provider = metric_provider
        self._metric_bindings = tuple(metric_bindings)
        self._workload_reader = workload_reader
        self._slo_reader = slo_reader
        self._dependency_paths = dict(dependency_paths)
        self._window = window
        self._clock = clock or (lambda: datetime.now(UTC))

    async def collect(self, service_id: str) -> AksCommerceEvidenceFrame:
        """Collect every configured source; provider failures remain explicit gaps."""

        typed_service_id: Literal["catalog-browse", "order-fulfillment"]
        if service_id == "catalog-browse":
            typed_service_id = "catalog-browse"
        elif service_id == "order-fulfillment":
            typed_service_id = "order-fulfillment"
        else:
            raise ValueError(f"AKS commerce service {service_id!r} is unsupported")
        end = self._clock()
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("AKS commerce observation clock must be timezone-aware")
        start = end - self._window
        dependency_path = self._dependency_paths.get(service_id)
        if dependency_path is None:
            raise ValueError(f"AKS commerce service {service_id!r} has no dependency path")
        workload_set = await self._workload_reader.read(service_id, cutoff=end)
        slos = await self._slo_reader.read(service_id, start=start, end=end)
        metrics: list[AksCommerceMetric] = []
        gaps = list(workload_set.gaps)
        for binding in self._metric_bindings:
            try:
                points = [
                    point
                    async for point in self._metric_provider.query(
                        MetricQuery(
                            metric_name=binding.name,
                            labels={"resource_id": binding.resource_ref},
                            since=start,
                            until=end,
                        )
                    )
                ]
            except MetricProviderError as exc:
                gaps.append(f"metric_provider.{binding.name}.{exc.reason.value}")
                metrics.append(_unavailable_metric(binding, end))
                continue
            metric, metric_gap = _reduce_metric(binding, points, start=start, end=end)
            metrics.append(metric)
            if metric_gap is not None:
                gaps.append(metric_gap)
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *workload_set.evidence_refs,
                    *(metric.source_ref for metric in metrics),
                    *(slo.source_ref for slo in slos),
                )
            )
        )
        return AksCommerceEvidenceFrame(
            service_id=typed_service_id,
            observed_at=end,
            window_start=start,
            window_end=end,
            dependency_path=dependency_path,
            workloads=workload_set.workloads,
            slos=slos,
            metrics=tuple(metrics),
            evidence_refs=evidence_refs,
            evidence_gaps=tuple(dict.fromkeys(gaps)),
            deployment_changed=workload_set.deployment_changed,
            rollout_stalled=workload_set.rollout_stalled,
            order_store_pressure=_database_pressure(metrics),
            synthetic=any(metric.synthetic for metric in metrics),
        )


def _reduce_metric(
    binding: CommerceMetricBinding,
    points: Sequence[MetricPoint],
    *,
    start: datetime,
    end: datetime,
) -> tuple[AksCommerceMetric, str | None]:
    qualified = tuple(
        point
        for point in points
        if point.metric_name == binding.name
        and point.at.tzinfo is not None
        and start <= point.at <= end
        and point.labels.get("resource_id") == binding.resource_ref
    )
    if len(qualified) != len(points):
        return _unavailable_metric(binding, end), f"metric_conflict.{binding.name}"
    if not qualified:
        return _unavailable_metric(binding, end), f"metric_empty.{binding.name}"
    midpoint = start + ((end - start) / 2)
    previous_points = tuple(point.value for point in qualified if point.at < midpoint)
    current_points = tuple(point.value for point in qualified if point.at >= midpoint)
    if not previous_points or not current_points:
        return _unavailable_metric(binding, end), f"metric_window_incomplete.{binding.name}"
    return (
        AksCommerceMetric(
            name=binding.name,
            unit=binding.unit,
            current=_reduce_values(current_points, binding.reduction),
            previous=_reduce_values(previous_points, binding.reduction),
            source_ref=binding.source_ref,
            observed_at=max(point.at for point in qualified),
            state=AksCommerceEvidenceState.COMPLETE,
            synthetic=binding.synthetic,
        ),
        None,
    )


def _reduce_values(values: tuple[float, ...], reduction: str) -> float:
    return float(sum(values) if reduction == "sum" else values[-1])


def _unavailable_metric(binding: CommerceMetricBinding, observed_at: datetime) -> AksCommerceMetric:
    return AksCommerceMetric(
        name=binding.name,
        unit=binding.unit,
        current=None,
        previous=None,
        source_ref=binding.source_ref,
        observed_at=observed_at,
        state=AksCommerceEvidenceState.UNAVAILABLE,
        synthetic=binding.synthetic,
    )


def _database_pressure(metrics: Sequence[AksCommerceMetric]) -> bool:
    for metric in metrics:
        if (
            metric.name == "database.normalized_ru_consumption"
            and metric.current is not None
            and metric.current >= 90
        ):
            return True
    return False


__all__ = [
    "CommerceMetricBinding",
    "CommerceSloEvidenceReader",
    "CommerceWorkloadEvidenceReader",
    "MetricCommerceObservationSource",
    "WorkloadEvidenceSet",
]
