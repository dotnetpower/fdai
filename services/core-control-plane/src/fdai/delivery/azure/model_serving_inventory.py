"""Enrich model deployments with bounded passive serving observations."""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol

from fdai_service_contracts.recorded_resource_state import (
    STATE_FACT_UNAVAILABLE_REASONS_PROPERTY,
)

from fdai.delivery.azure.model_deployment import MODEL_DEPLOYMENT_RESOURCE_TYPE
from fdai.delivery.azure.model_serving_state import (
    MODEL_SERVING_SOURCE_IDENTITY,
    MODEL_SERVING_STATE_PROPERTY,
    carry_model_serving_or_reason,
    model_deployment_name,
    model_serving_evidence_ref,
    model_serving_reason_map,
    prior_model_serving_resource,
    retain_model_serving_or_reason,
    valid_model_serving_point,
)
from fdai.delivery.inventory_sync import (
    InventoryProjectionSourceState,
    InventoryProjectionSourceStatus,
    PromotedInventoryObservation,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.metric import (
    MetricFailureReason,
    MetricPoint,
    MetricProvider,
    MetricProviderError,
    MetricQuery,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

MODEL_SERVING_INVENTORY_SOURCE_NAME: Final = "azure_model_serving_metrics"
MODEL_SERVING_METRIC_NAME: Final = "model.response.200.count"
_PREVIOUS_STATE_READ_BATCH = 1000


@dataclass(frozen=True, slots=True)
class AzureModelServingInventoryConfig:
    """Bound passive metric reads for exact model deployment targets."""

    lookback_seconds: int = 300
    freshness_ceiling_seconds: int = 600
    max_targets: int = 200
    max_concurrency: int = 8
    max_points_per_target: int = 32
    per_request_timeout_seconds: float = 10.0
    total_timeout_seconds: float = 250.0

    def __post_init__(self) -> None:
        if not 60 <= self.lookback_seconds <= 21_600:
            raise ValueError("model serving lookback_seconds MUST be in [60, 21600]")
        if self.freshness_ceiling_seconds < self.lookback_seconds:
            raise ValueError("model serving freshness ceiling MUST cover the lookback")
        if not 1 <= self.max_targets <= 1000:
            raise ValueError("model serving max_targets MUST be in [1, 1000]")
        if not 1 <= self.max_concurrency <= 8:
            raise ValueError("model serving max_concurrency MUST be in [1, 8]")
        if not 1 <= self.max_points_per_target <= 1000:
            raise ValueError("model serving max_points_per_target MUST be in [1, 1000]")
        required_points = math.ceil(self.lookback_seconds / 60) + 1
        if self.max_points_per_target < required_points:
            raise ValueError("model serving point cap MUST cover every one-minute window bucket")
        if not 0.1 <= self.per_request_timeout_seconds <= 30:
            raise ValueError("model serving request timeout MUST be in [0.1, 30]")
        if not 0.1 <= self.total_timeout_seconds <= 900:
            raise ValueError("model serving total timeout MUST be in [0.1, 900]")
        required_timeout = (
            math.ceil(self.max_targets / self.max_concurrency) * self.per_request_timeout_seconds
        )
        if self.total_timeout_seconds < required_timeout:
            raise ValueError("model serving total timeout MUST cover the configured fan-out")


@dataclass(frozen=True, slots=True)
class _ServingFact:
    effective_at: datetime
    evidence_ref: str


class ModelServingPreviousStateReader(Protocol):
    """Read exact active Resources without granting write authority."""

    async def read_active_resources(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]: ...


class AzureModelServingInventoryEnricher:
    """Record recent exact deployment success without invoking a model."""

    def __init__(
        self,
        *,
        provider: MetricProvider,
        config: AzureModelServingInventoryConfig | None = None,
        previous_state_reader: ModelServingPreviousStateReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or AzureModelServingInventoryConfig()
        self._previous_state_reader = previous_state_reader
        self._clock = clock or (lambda: datetime.now(UTC))

    async def enrich(
        self,
        observation: PromotedInventoryObservation,
    ) -> PromotedInventoryObservation:
        targets = tuple(
            sorted(
                (
                    item
                    for item in observation.resources
                    if item.type == MODEL_DEPLOYMENT_RESOURCE_TYPE
                ),
                key=lambda item: item.resource_id,
            )
        )
        base_generation, previous = (
            await self._read_previous(targets)
            if self._previous_state_reader is not None
            else (None, {})
        )
        base = replace(
            observation,
            state_base_generation=base_generation,
            state_base_generation_checked=self._previous_state_reader is not None,
        )
        if not observation.complete:
            evaluated_at = self._now()
            return self._source_unavailable(
                retain_model_serving_or_reason(
                    base,
                    previous,
                    "model_serving_source_unavailable",
                    evaluated_at=evaluated_at,
                ),
                reason="inventory_generation_incomplete",
                coverage={"targets": len(targets)},
            )
        if not targets:
            return self._source_available(base, observed_at=self._now(), coverage={"targets": 0})

        selected = targets[: self._config.max_targets]
        limited = targets[self._config.max_targets :]
        until = self._now()
        since = until - timedelta(seconds=self._config.lookback_seconds)
        semaphore = asyncio.Semaphore(self._config.max_concurrency)

        async def collect(resource: ResourceRecord) -> tuple[ResourceRecord, _ServingFact | str]:
            async with semaphore:
                return resource, await self._read(resource, since=since, until=until)

        tasks = {asyncio.create_task(collect(resource)): resource for resource in selected}
        completed, pending = await asyncio.wait(
            tuple(tasks),
            timeout=self._config.total_timeout_seconds,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        results = sorted(
            (task.result() for task in completed),
            key=lambda item: item[0].resource_id,
        )

        completed_at = self._now()
        coverage: Counter[str] = Counter()
        retained: dict[str, ResourceRecord] = {}
        facts: dict[str, _ServingFact] = {}
        for resource in limited:
            coverage["target_limit"] += 1
            retained[resource.resource_id] = carry_model_serving_or_reason(
                resource,
                previous.get(resource.resource_id),
                "model_serving_target_limit",
                evaluated_at=completed_at,
            )
        for task in pending:
            resource = tasks[task]
            coverage["source_unavailable"] += 1
            retained[resource.resource_id] = carry_model_serving_or_reason(
                resource,
                previous.get(resource.resource_id),
                "model_serving_source_unavailable",
                evaluated_at=completed_at,
            )
        for resource, result in results:
            if isinstance(result, str):
                coverage[result] += 1
                retained[resource.resource_id] = carry_model_serving_or_reason(
                    resource,
                    previous.get(resource.resource_id),
                    f"model_serving_{result}",
                    evaluated_at=completed_at,
                )
                continue
            prior = prior_model_serving_resource(previous.get(resource.resource_id))
            if result.effective_at > completed_at:
                coverage["response_invalid"] += 1
                retained[resource.resource_id] = carry_model_serving_or_reason(
                    resource,
                    previous.get(resource.resource_id),
                    "model_serving_response_invalid",
                    evaluated_at=completed_at,
                )
                continue
            if prior is not None and result.effective_at < prior[1].effective_at:
                coverage["out_of_order"] += 1
                retained[resource.resource_id] = carry_model_serving_or_reason(
                    resource,
                    previous.get(resource.resource_id),
                    "model_serving_response_invalid",
                    evaluated_at=completed_at,
                )
                continue
            coverage["observed"] += 1
            facts[resource.resource_id] = result

        updated = tuple(
            self._with_fact(resource, facts[resource.resource_id], completed_at=completed_at)
            if resource.resource_id in facts
            else retained.get(resource.resource_id, resource)
            for resource in observation.resources
        )
        enriched = replace(base, resources=updated, recorded_at=completed_at)
        counts = {"targets": len(targets), **dict(sorted(coverage.items()))}
        source_failures = sum(
            count
            for reason, count in coverage.items()
            if reason
            not in {
                "not_observed",
                "observed",
                "out_of_order",
            }
        )
        if source_failures:
            return self._source_unavailable(
                enriched,
                reason="model_serving_partial",
                coverage=counts,
            )
        return self._source_available(enriched, observed_at=completed_at, coverage=counts)

    async def _read_previous(
        self,
        targets: tuple[ResourceRecord, ...],
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]:
        if self._previous_state_reader is None:
            return None, {}
        generation: str | None = None
        previous: dict[str, ResourceRecord] = {}
        resource_ids = tuple(item.resource_id for item in targets)
        if not resource_ids:
            return await self._previous_state_reader.read_active_resources(resource_ids=())
        for index in range(0, len(resource_ids), _PREVIOUS_STATE_READ_BATCH):
            batch_generation, batch = await self._previous_state_reader.read_active_resources(
                resource_ids=resource_ids[index : index + _PREVIOUS_STATE_READ_BATCH]
            )
            if index > 0 and batch_generation != generation:
                return None, {}
            generation = batch_generation
            previous.update(batch)
        return generation, previous

    async def _read(
        self,
        resource: ResourceRecord,
        *,
        since: datetime,
        until: datetime,
    ) -> _ServingFact | str:
        provider_ref = resource.provider_ref
        deployment_name = model_deployment_name(provider_ref)
        if provider_ref is None or deployment_name is None:
            return "target_unresolved"
        points: list[MetricPoint] = []
        try:
            async for point in self._provider.query(
                MetricQuery(
                    metric_name=MODEL_SERVING_METRIC_NAME,
                    labels={"resource_id": provider_ref},
                    since=since,
                    until=until,
                )
            ):
                points.append(point)
                if len(points) > self._config.max_points_per_target:
                    return "response_invalid"
        except MetricProviderError as exc:
            if exc.reason is MetricFailureReason.INVALID_QUERY:
                return "target_unresolved"
            if exc.reason in {
                MetricFailureReason.INVALID_RESPONSE,
                MetricFailureReason.RESPONSE_LIMIT,
            }:
                return "response_invalid"
            return "source_unavailable"
        except Exception:  # noqa: BLE001 - optional provider details must not block inventory
            return "source_unavailable"
        if any(
            not valid_model_serving_point(
                point,
                metric_name=MODEL_SERVING_METRIC_NAME,
                provider_ref=provider_ref,
                deployment_name=deployment_name,
                since=since,
                until=until,
            )
            for point in points
        ):
            return "response_invalid"
        positive = [point for point in points if point.value > 0]
        if not positive:
            return "not_observed"
        latest = max(positive, key=lambda point: point.at)
        return _ServingFact(
            effective_at=latest.at.astimezone(UTC),
            evidence_ref=model_serving_evidence_ref(
                resource_id=resource.resource_id,
                effective_at=latest.at,
                value=latest.value,
                metric_name=MODEL_SERVING_METRIC_NAME,
            ),
        )

    def _with_fact(
        self,
        resource: ResourceRecord,
        fact: _ServingFact,
        *,
        completed_at: datetime,
    ) -> ResourceRecord:
        props = dict(resource.props)
        raw_metadata = props.get(STATE_FACT_METADATA_PROPERTY)
        metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}
        metadata[MODEL_SERVING_STATE_PROPERTY] = StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.TELEMETRY,
            source_identity=MODEL_SERVING_SOURCE_IDENTITY,
            source_revision=fact.evidence_ref,
            effective_at=fact.effective_at,
            recorded_at=completed_at,
            evidence_cutoff=completed_at,
            freshness_ceiling_seconds=self._config.freshness_ceiling_seconds,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(fact.evidence_ref,),
        ).to_mapping()
        reasons = model_serving_reason_map(props)
        reasons.pop(MODEL_SERVING_STATE_PROPERTY, None)
        props[MODEL_SERVING_STATE_PROPERTY] = "Serving"
        props[STATE_FACT_METADATA_PROPERTY] = metadata
        if reasons:
            props[STATE_FACT_UNAVAILABLE_REASONS_PROPERTY] = reasons
        else:
            props.pop(STATE_FACT_UNAVAILABLE_REASONS_PROPERTY, None)
        return replace(resource, props=props)

    @staticmethod
    def _source_available(
        observation: PromotedInventoryObservation,
        *,
        observed_at: datetime,
        coverage: Mapping[str, int],
    ) -> PromotedInventoryObservation:
        return replace(
            observation,
            source_states=(
                *observation.source_states,
                InventoryProjectionSourceState(
                    source=MODEL_SERVING_INVENTORY_SOURCE_NAME,
                    status=InventoryProjectionSourceStatus.AVAILABLE,
                    observed_at=observed_at,
                    reason=None,
                    coverage=coverage,
                ),
            ),
        )

    @staticmethod
    def _source_unavailable(
        observation: PromotedInventoryObservation,
        *,
        reason: str,
        coverage: Mapping[str, int],
    ) -> PromotedInventoryObservation:
        return replace(
            observation,
            source_states=(
                *observation.source_states,
                InventoryProjectionSourceState(
                    source=MODEL_SERVING_INVENTORY_SOURCE_NAME,
                    status=InventoryProjectionSourceStatus.UNAVAILABLE,
                    observed_at=None,
                    reason=reason,
                    coverage=coverage,
                ),
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("model serving clock MUST be timezone-aware")
        return value.astimezone(UTC)


__all__ = [
    "AzureModelServingInventoryConfig",
    "AzureModelServingInventoryEnricher",
    "MODEL_SERVING_INVENTORY_SOURCE_NAME",
    "MODEL_SERVING_METRIC_NAME",
    "MODEL_SERVING_STATE_PROPERTY",
    "ModelServingPreviousStateReader",
]
