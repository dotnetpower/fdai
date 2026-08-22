"""Bounded Azure Resource Graph reader for secured Resource Health collections."""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx

from fdai.core.ontology_platform.resource_health_queries import (
    ResourceHealthCollection,
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
        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("Resource Health reader clock MUST be timezone-aware")
        if (
            requested != resource_ids
            or not requested
            or len(requested) > self._config.max_resources
        ):
            raise ValueError("Resource Health resource_ids MUST be ordered within the server bound")
        try:
            arm_by_resource = {
                resource_id: azure_arm_resource_id(
                    resource_id,
                    subscription_id=self._config.subscription_id,
                )
                for resource_id in requested
            }
        except ValueError:
            return self._result(
                requested,
                observed_at=observed_at,
                observations=(),
                complete=False,
                limitation="target_identity_unavailable",
            )
        resource_by_arm = {
            arm_id.casefold(): resource_id for resource_id, arm_id in arm_by_resource.items()
        }
        batches = tuple(_chunks(tuple(resource_by_arm), _BATCH_SIZE))
        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        async def read_batch(batch: tuple[str, ...]) -> tuple[Mapping[str, Any], ...]:
            async with semaphore:
                return await fetch_arg_row_pages(
                    identity=self._identity,
                    http_client=self._http,
                    audience=_MANAGEMENT_AUDIENCE,
                    endpoint=self._config.endpoint,
                    api_version=_ARG_API_VERSION,
                    subscriptions=(self._config.subscription_id,),
                    query=_health_query(batch),
                    result_name="semantic-resource-health",
                    page_size=len(batch) + 1,
                    max_pages=1,
                    max_records=len(batch) + 1,
                    timeout_seconds=self._config.timeout_seconds,
                    error_type=ResourceHealthCollectionError,
                    throttle_gate=self._throttle_gate,
                    rate_limiter=self._rate_limiter,
                    max_response_bytes=self._config.max_response_bytes,
                    max_total_response_bytes=self._config.max_response_bytes,
                )

        batch_results = await asyncio.gather(
            *(read_batch(batch) for batch in batches),
            return_exceptions=True,
        )
        failed_batches = sum(isinstance(result, Exception) for result in batch_results)
        rows = tuple(row for result in batch_results if isinstance(result, tuple) for row in result)
        if failed_batches == len(batches):
            return self._result(
                requested,
                observed_at=observed_at,
                observations=(),
                complete=False,
                limitation="source_unavailable",
            )
        observations: list[ResourceHealthObservation] = []
        observed_resource_ids: list[str] = []
        malformed = False
        widened = False
        for row in rows:
            target = row.get("targetResourceId")
            if not isinstance(target, str):
                malformed = True
                continue
            resource_id = resource_by_arm.get(target.casefold())
            if resource_id is None:
                widened = True
                continue
            observation = _observation(row, resource_id=resource_id, fallback_time=observed_at)
            if observation is None:
                malformed = True
                continue
            observations.append(observation)
            observed_resource_ids.append(resource_id)
        duplicates = {key for key, count in Counter(observed_resource_ids).items() if count > 1}
        if duplicates:
            observations = [item for item in observations if item.resource_id not in duplicates]
        observed_set = {item.resource_id for item in observations}
        missing = set(requested) - observed_set
        limitation = (
            "provider_scope_mismatch"
            if widened
            else "resource_health_conflict"
            if duplicates
            else "resource_health_response_invalid"
            if malformed
            else "resource_health_coverage_incomplete"
            if failed_batches
            else "resource_health_coverage_incomplete"
            if missing
            else None
        )
        return self._result(
            requested,
            observed_at=observed_at,
            observations=tuple(sorted(observations, key=lambda item: item.resource_id)),
            complete=limitation is None,
            limitation=limitation,
        )

    def _result(
        self,
        resource_ids: tuple[str, ...],
        *,
        observed_at: datetime,
        observations: tuple[ResourceHealthObservation, ...],
        complete: bool,
        limitation: str | None,
    ) -> ResourceHealthCollection:
        material = "|".join(
            (
                *resource_ids,
                observed_at.isoformat(),
                "complete" if complete else limitation or "incomplete",
            )
        )
        return ResourceHealthCollection(
            resource_ids=resource_ids,
            observations=observations,
            observed_at=observed_at,
            complete=complete,
            limitation=limitation,
            attempt_ref=f"azure-resource-health-query:{hashlib.sha256(material.encode()).hexdigest()}",
        )


def _health_query(arm_ids: tuple[str, ...]) -> str:
    values = ", ".join(f"'{_kusto_literal(item)}'" for item in arm_ids)
    return (
        "HealthResources "
        "| where type =~ 'microsoft.resourcehealth/availabilitystatuses' "
        f"| where tostring(properties.targetResourceId) in~ ({values}) "
        "| project targetResourceId=tostring(properties.targetResourceId), "
        "availabilityState=tostring(properties.availabilityState), "
        "reasonType=tostring(properties.reasonType), "
        "occurredTime=tostring(properties.occurredTime), "
        "reportedTime=tostring(properties.reportedTime) "
        f"| take {len(arm_ids) + 1}"
    )


def _chunks(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _observation(
    row: Mapping[str, Any],
    *,
    resource_id: str,
    fallback_time: datetime,
) -> ResourceHealthObservation | None:
    state = row.get("availabilityState")
    if not isinstance(state, str) or not state.strip():
        return None
    observed_at = _timestamp(row.get("reportedTime")) or _timestamp(row.get("occurredTime"))
    if observed_at is None:
        observed_at = fallback_time
    reason = _health_kind(row.get("reasonType"))
    evidence_material = f"{resource_id}|{state}|{reason}|{observed_at.isoformat()}"
    return ResourceHealthObservation(
        resource_id=resource_id,
        availability_state=_machine_token(state, fallback="unknown"),
        reason_kind=reason,
        observed_at=observed_at,
        evidence_ref=(
            f"azure-resource-health:{hashlib.sha256(evidence_material.encode()).hexdigest()}"
        ),
    )


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


def _kusto_literal(value: str) -> str:
    return value.replace("'", "''")


__all__ = [
    "AzureResourceHealthCollectionConfig",
    "AzureResourceHealthCollectionReader",
    "ResourceHealthCollectionError",
]
