"""MetricProvider adapter for exact reviewed ontology metric windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.metric_semantics import (
    MetricSemanticDefinition,
    MetricWindow,
)
from fdai.shared.providers.metric import MetricPoint, MetricProvider, MetricQuery


@dataclass(frozen=True, slots=True)
class MetricWindowCoveragePolicy:
    """Server-owned minimum observation policy for absence and completeness."""

    minimum_samples: int = 1
    maximum_samples: int = 10_000

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_samples <= self.maximum_samples <= 10_000:
            raise ValueError("metric window coverage bounds are invalid")


class ProviderMetricWindowReader:
    """Read a bounded exact provider metric and issue an honest completeness state."""

    def __init__(
        self,
        *,
        provider: MetricProvider,
        coverage: MetricWindowCoveragePolicy | None = None,
    ) -> None:
        self._provider = provider
        self._coverage = coverage or MetricWindowCoveragePolicy()

    async def read(
        self,
        *,
        definition: MetricSemanticDefinition,
        resource_id: str,
        start: datetime,
        end: datetime,
    ) -> MetricWindow:
        """Return provider samples or an explicit incomplete window, never inferred zero."""

        query = MetricQuery(
            metric_name=definition.provider_metric,
            labels={"resource_id": resource_id},
            since=start,
            until=end,
            aggregation=definition.aggregation.value,
        )
        points: list[MetricPoint] = []
        truncated = False
        async for point in self._provider.query(query):
            if point.metric_name != definition.provider_metric:
                raise ValueError("metric provider returned another metric")
            if point.labels.get("resource_id") != resource_id:
                raise ValueError("metric provider returned another resource")
            if len(points) >= self._coverage.maximum_samples:
                truncated = True
                break
            points.append(point)
        points.sort(key=lambda item: item.at)
        if len({item.at for item in points}) != len(points):
            raise ValueError("metric provider returned duplicate timestamps")
        complete = len(points) >= self._coverage.minimum_samples and not truncated
        if truncated:
            reason = "sample_limit"
        elif not complete:
            reason = "provider_gap"
        else:
            reason = None
        evidence_refs = (
            f"metric-provider:{definition.concept_id}:{start.isoformat()}:{end.isoformat()}",
        )
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=tuple(MetricSample(timestamp=item.at, value=item.value) for item in points),
            complete=complete,
            missing_reason=reason,
            evidence_refs=evidence_refs,
        )


__all__ = ["MetricWindowCoveragePolicy", "ProviderMetricWindowReader"]
