"""Bounded Azure Resource Graph reader for secured Resource Health collections."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx

from fdai.core.ontology_platform.resource_health_queries import (
    ResourceHealthAvailabilityState,
    ResourceHealthCollection,
    ResourceHealthCoverage,
    ResourceHealthCoverageStatus,
    ResourceHealthObservation,
)
from fdai.delivery.azure.arg_transport import (
    ArgRateLimiter,
    ArgThrottleGate,
    fetch_arg_row_pages,
)
from fdai.delivery.azure.metric_window import azure_arm_resource_id
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_ARG_API_VERSION: Final = "2022-10-01"
_BATCH_SIZE = 64
_DUPLICATE_HEADROOM = 2


class ResourceHealthCollectionError(RuntimeError):
    """Report a bounded provider failure without retaining response content."""


@dataclass(frozen=True, slots=True)
class AzureResourceHealthCollectionConfig:
    """Server-owned subscription and request ceilings for collection health reads."""

    subscription_id: str
    endpoint: str = "https://management.azure.com"
    timeout_seconds: float = 10.0
    max_resources: int = 1000
    max_concurrent_queries: int = 4
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.subscription_id))
        except (AttributeError, ValueError) as exc:
            raise ValueError("subscription_id MUST be a canonical UUID") from exc
        if canonical != self.subscription_id.casefold():
            raise ValueError("subscription_id MUST be a canonical UUID")
        if not self.endpoint.startswith("https://"):
            raise ValueError("Resource Health endpoint MUST use https")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("Resource Health timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.max_resources <= 1000:
            raise ValueError("Resource Health max_resources MUST be in [1, 1000]")
        if not 1 <= self.max_concurrent_queries <= 8:
            raise ValueError("Resource Health max_concurrent_queries MUST be in [1, 8]")
        if not 1_024 <= self.max_response_bytes <= 5_000_000:
            raise ValueError("Resource Health max_response_bytes MUST be in [1024, 5000000]")


class AzureResourceHealthCollectionReader:
    """Read current health for exact ontology resources under one fixed subscription."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureResourceHealthCollectionConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity: Final = identity
        self._http: Final = http_client
        self._config: Final = config
        self._now: Final = now or (lambda: datetime.now(UTC))
        self._throttle_gate = ArgThrottleGate()
        self._rate_limiter = ArgRateLimiter()

    async def read_current(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> ResourceHealthCollection:
        """Return current Resource Health rows without accepting caller provider scope."""

        requested = tuple(sorted(set(resource_ids)))
        started_at = self._now()
        if started_at.tzinfo is None:
            raise ValueError("Resource Health reader clock MUST be timezone-aware")
        if (
            requested != resource_ids
            or not requested
            or len(requested) > self._config.max_resources
        ):
            raise ValueError("Resource Health resource_ids MUST be ordered within the server bound")
        arm_groups: dict[str, list[str]] = defaultdict(list)
        coverage_by_resource: dict[str, ResourceHealthCoverageStatus] = {}
        for resource_id in requested:
            try:
                arm_id = azure_arm_resource_id(
                    resource_id,
                    subscription_id=self._config.subscription_id,
                )
            except ValueError:
                coverage_by_resource[resource_id] = ResourceHealthCoverageStatus.TARGET_UNRESOLVED
                continue
            arm_groups[arm_id.casefold()].append(resource_id)
        resource_by_arm: dict[str, str] = {}
        for arm_id, resource_ids_for_arm in arm_groups.items():
            if len(resource_ids_for_arm) > 1:
                for resource_id in resource_ids_for_arm:
                    coverage_by_resource[resource_id] = (
                        ResourceHealthCoverageStatus.TARGET_UNRESOLVED
                    )
                continue
            resource_by_arm[arm_id] = resource_ids_for_arm[0]
        batches = tuple(_chunks(tuple(resource_by_arm), _BATCH_SIZE))
        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        async def read_batch(batch: tuple[str, ...]) -> tuple[Mapping[str, Any], ...]:
            query_limit = _query_limit(len(batch))
            async with semaphore:
                return await fetch_arg_row_pages(
                    identity=self._identity,
                    http_client=self._http,
                    audience=_MANAGEMENT_AUDIENCE,
                    endpoint=self._config.endpoint,
                    api_version=_ARG_API_VERSION,
                    subscriptions=(self._config.subscription_id,),
                    query=_health_query(batch, row_limit=query_limit),
                    result_name="semantic-resource-health",
                    page_size=query_limit,
                    max_pages=1,
                    max_records=query_limit,
                    timeout_seconds=self._config.timeout_seconds,
                    error_type=ResourceHealthCollectionError,
                    throttle_gate=self._throttle_gate,
                    rate_limiter=self._rate_limiter,
                    max_response_bytes=self._config.max_response_bytes,
                    max_total_response_bytes=self._config.max_response_bytes,
                )

        batch_results = (
            await asyncio.gather(
                *(read_batch(batch) for batch in batches),
                return_exceptions=True,
            )
            if batches
            else ()
        )
        observations: list[ResourceHealthObservation] = []
        issues: set[str] = set()
        for batch, result in zip(batches, batch_results, strict=True):
            batch_resources = tuple(resource_by_arm[arm_id] for arm_id in batch)
            if isinstance(result, BaseException):
                for resource_id in batch_resources:
                    coverage_by_resource[resource_id] = (
                        ResourceHealthCoverageStatus.SCOPE_UNREADABLE
                    )
                continue
            query_limit = _query_limit(len(batch))
            if len(result) >= query_limit:
                for resource_id in batch_resources:
                    coverage_by_resource[resource_id] = (
                        ResourceHealthCoverageStatus.RESPONSE_TRUNCATED
                    )
                continue
            rows_by_resource: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            batch_set = set(batch)
            for row in result:
                target = row.get("targetResourceId")
                if not isinstance(target, str):
                    issues.add("response_invalid")
                    continue
                folded_target = target.casefold()
                if folded_target not in batch_set:
                    issues.add("provider_scope_mismatch")
                    continue
                rows_by_resource[resource_by_arm[folded_target]].append(row)
            for resource_id in batch_resources:
                resource_rows = rows_by_resource.get(resource_id, [])
                if not resource_rows:
                    coverage_by_resource[resource_id] = ResourceHealthCoverageStatus.NO_RECORD
                    continue
                if len(resource_rows) > 1:
                    coverage_by_resource[resource_id] = (
                        ResourceHealthCoverageStatus.DUPLICATE_RECORD
                    )
                    continue
                observation, status = _observation(
                    resource_rows[0],
                    resource_id=resource_id,
                )
                coverage_by_resource[resource_id] = status
                if observation is not None:
                    observations.append(observation)
        coverage = tuple(
            ResourceHealthCoverage(
                resource_id=resource_id,
                status=coverage_by_resource.get(
                    resource_id,
                    ResourceHealthCoverageStatus.RESPONSE_INVALID,
                ),
            )
            for resource_id in requested
        )
        return self._result(
            requested,
            started_at=started_at,
            observations=tuple(sorted(observations, key=lambda item: item.resource_id)),
            coverage=coverage,
            issues=tuple(sorted(issues)),
        )

    def _result(
        self,
        resource_ids: tuple[str, ...],
        *,
        started_at: datetime,
        observations: tuple[ResourceHealthObservation, ...],
        coverage: tuple[ResourceHealthCoverage, ...],
        issues: tuple[str, ...],
    ) -> ResourceHealthCollection:
        completed_at = self._now()
        material = "|".join(
            (
                *resource_ids,
                started_at.isoformat(),
                completed_at.isoformat(),
                *(f"{item.resource_id}:{item.status.value}" for item in coverage),
                *issues,
            )
        )
        return ResourceHealthCollection(
            resource_ids=resource_ids,
            observations=observations,
            coverage=coverage,
            started_at=started_at,
            completed_at=completed_at,
            attempt_ref=f"azure-resource-health-query:{hashlib.sha256(material.encode()).hexdigest()}",
            issues=issues,
        )


def _health_query(arm_ids: tuple[str, ...], *, row_limit: int) -> str:
    values = json.dumps(arm_ids, separators=(",", ":"))
    return (
        f"let targetResourceIds = dynamic({values}); "
        "HealthResources "
        "| where type =~ 'microsoft.resourcehealth/availabilitystatuses' "
        "| where tostring(properties['targetResourceId']) in~ (targetResourceIds) "
        "| project targetResourceId=tostring(properties['targetResourceId']), "
        "availabilityState=tostring(properties['availabilityState']), "
        "reasonType=tostring(properties['reasonType']), "
        "occurredTime=tostring(properties['occurredTime']), "
        "reportedTime=tostring(properties['reportedTime']) "
        f"| take {row_limit}"
    )


def _chunks(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _query_limit(batch_size: int) -> int:
    return batch_size * _DUPLICATE_HEADROOM + 1


def _observation(
    row: Mapping[str, Any],
    *,
    resource_id: str,
) -> tuple[ResourceHealthObservation | None, ResourceHealthCoverageStatus]:
    state = row.get("availabilityState")
    if not isinstance(state, str):
        return None, ResourceHealthCoverageStatus.RESPONSE_INVALID
    normalized_state = _machine_token(state, fallback="state_absent")
    try:
        availability_state = ResourceHealthAvailabilityState(normalized_state)
    except ValueError:
        return None, ResourceHealthCoverageStatus.RESPONSE_INVALID
    provider_observed_at, invalid_time = _provider_time(row)
    if invalid_time:
        return None, ResourceHealthCoverageStatus.RESPONSE_INVALID
    reason = _health_kind(row.get("reasonType"))
    evidence_material = (
        f"{resource_id}|{availability_state.value}|{reason}|"
        f"{provider_observed_at.isoformat() if provider_observed_at is not None else 'time_absent'}"
    )
    observation = ResourceHealthObservation(
        resource_id=resource_id,
        availability_state=availability_state,
        reason_kind=reason,
        provider_observed_at=provider_observed_at,
        evidence_ref=(
            f"azure-resource-health:{hashlib.sha256(evidence_material.encode()).hexdigest()}"
        ),
    )
    if availability_state is ResourceHealthAvailabilityState.STATE_ABSENT:
        return observation, ResourceHealthCoverageStatus.STATE_ABSENT
    if provider_observed_at is None:
        return observation, ResourceHealthCoverageStatus.RESPONSE_INVALID
    return observation, ResourceHealthCoverageStatus.OBSERVED


def _provider_time(row: Mapping[str, Any]) -> tuple[datetime | None, bool]:
    saw_invalid = False
    for field in ("reportedTime", "occurredTime"):
        value = row.get(field)
        if value is None or value == "":
            continue
        parsed = _timestamp(value)
        if parsed is not None:
            return parsed, False
        saw_invalid = True
    return None, saw_invalid


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _machine_token(value: object, *, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    normalized = "_".join(value.casefold().replace("-", " ").split())
    return normalized[:64] or fallback


def _health_kind(value: object) -> str:
    normalized = _machine_token(value, fallback="status_only")
    if normalized in {"platform_initiated", "platforminitiated"}:
        return "platform_initiated"
    if normalized in {
        "customer_initiated",
        "customerinitiated",
        "user_initiated",
        "userinitiated",
    }:
        return "customer_initiated"
    return normalized


__all__ = [
    "AzureResourceHealthCollectionConfig",
    "AzureResourceHealthCollectionReader",
    "ResourceHealthCollectionError",
]
