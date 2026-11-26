"""Read reviewed capacity metrics for exact current inventory identities."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from fdai.agents import MAX_RECURRING_SAMPLES, UtilizationSample, stable_idempotency_key
from fdai.core.ontology_platform.metric_semantics import MetricSemanticRegistry
from fdai.delivery.analyzer_inventory import (
    AnalyzerProviderReferenceReader,
    read_provider_query_references,
)
from fdai.delivery.analyzer_metric_provider import AnalyzerMetricProvider
from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.shared.providers.metric import MetricPoint, MetricProvider, MetricQuery


class CapacityMetricSampler:
    """Read-only bounded source sampler; no default targets or fabricated observations."""

    def __init__(
        self,
        *,
        provider: MetricProvider,
        inventory: AnalyzerProviderReferenceReader,
        registry: MetricSemanticRegistry,
        targets: Mapping[str, str],
        max_age: timedelta = timedelta(minutes=5),
    ) -> None:
        metric = registry.resolve("resource.cpu.utilization_pct")
        if metric.canonical_unit != "percent" or metric.provider_metric != "host.cpu.percent":
            raise ValueError("capacity metric declaration is unsupported")
        if not 1 <= len(targets) <= MAX_RECURRING_SAMPLES or max_age <= timedelta(0):
            raise ValueError("capacity sampling targets or freshness bound is invalid")
        self._provider = provider
        self._inventory = inventory
        self._targets = dict(targets)
        self._metric = metric.provider_metric
        self._declaration_digest = registry.digest
        self._max_age = max_age

    async def read_utilization_samples(
        self,
        *,
        limit: int,
        observed_at: datetime,
    ) -> Sequence[UtilizationSample]:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("capacity sampling cutoff MUST be timezone-aware")
        if type(limit) is not int or limit < len(self._targets):
            raise ValueError("capacity sampling MUST NOT truncate configured targets")
        snapshot_id, _ = await self._inventory.read_active_resources(
            resource_ids=tuple(sorted(self._targets))
        )
        if snapshot_id is None:
            raise ValueError("capacity inventory generation is unavailable")
        references = await read_provider_query_references(
            self._inventory,
            expected_resource_types=self._targets,
            expected_snapshot_id=snapshot_id,
        )
        provider = AnalyzerMetricProvider(
            self._provider,
            targets=tuple(
                AnalyzerTarget(
                    resource_ref=resource_id,
                    resource_kind="capacity",
                    resource_type=self._targets[resource_id],
                    provider_query_ref=reference,
                )
                for resource_id, reference in references.items()
            ),
        )
        samples: list[UtilizationSample] = []
        for resource_id in sorted(self._targets):
            latest: MetricPoint | None = None
            points = 0
            async for point in provider.query(
                MetricQuery(
                    metric_name=self._metric,
                    labels={"resource_id": resource_id},
                    since=observed_at - self._max_age,
                    until=observed_at,
                )
            ):
                points += 1
                if points > 1_000:
                    raise ValueError("capacity metric source exceeded its bounded point count")
                if (
                    point.metric_name != self._metric
                    or point.labels.get("resource_id") != resource_id
                    or point.at.tzinfo is None
                    or point.at.utcoffset() is None
                    or not observed_at - self._max_age <= point.at <= observed_at
                    or isinstance(point.value, bool)
                    or not math.isfinite(point.value)
                    or not 0 <= point.value <= 100
                    or latest is not None
                    and point.at <= latest.at
                ):
                    raise ValueError("capacity metric source identity, value or time is invalid")
                latest = point
            if latest is None:
                continue
            sample_key = stable_idempotency_key(
                "freyr-source-metric",
                snapshot_id,
                resource_id,
                self._metric,
                self._declaration_digest,
                latest.at.isoformat(),
                latest.value,
            )
            samples.append(
                UtilizationSample(
                    resource_id=resource_id,
                    utilization=latest.value / 100,
                    observed_at=latest.at.isoformat(),
                    correlation_id=sample_key,
                    sample_key=sample_key,
                )
            )
        current_references = await read_provider_query_references(
            self._inventory,
            expected_resource_types=self._targets,
            expected_snapshot_id=snapshot_id,
        )
        if current_references != references:
            raise ValueError("capacity source references changed during metric observation")
        return tuple(samples)
