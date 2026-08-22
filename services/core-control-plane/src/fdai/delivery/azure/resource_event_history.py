"""Bounded Azure Resource Health history for secured Resource collections."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx

from fdai.core.ontology_platform.resource_event_queries import (
    RESOURCE_EVENT_MEASURE_CONCEPTS,
    ResourceEventCollection,
    ResourceEventObservation,
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
_MAX_EVENTS = 256
_BATCH_SIZE = 64


class ResourceEventHistoryError(RuntimeError):
    """Report a bounded provider failure without retaining provider content."""


@dataclass(frozen=True, slots=True)
class AzureResourceEventHistoryConfig:
    """Server-owned subscription and request ceilings for history reads."""

    subscription_id: str
    endpoint: str = "https://management.azure.com"
    timeout_seconds: float = 10.0
    max_resources: int = 1000
    max_concurrent_queries: int = 4
    max_response_bytes: int = 2_097_152

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.subscription_id))
        except (AttributeError, ValueError) as exc:
            raise ValueError("subscription_id MUST be a canonical UUID") from exc
        if canonical != self.subscription_id.casefold():
            raise ValueError("subscription_id MUST be a canonical UUID")
        if not self.endpoint.startswith("https://"):
            raise ValueError("Resource event endpoint MUST use https")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("Resource event timeout_seconds MUST be in [0.1, 30]")
        if not 1 <= self.max_resources <= 1000:
            raise ValueError("Resource event max_resources MUST be in [1, 1000]")
        if not 1 <= self.max_concurrent_queries <= 8:
            raise ValueError("Resource event max_concurrent_queries MUST be in [1, 8]")
        if not 1_024 <= self.max_response_bytes <= 5_000_000:
            raise ValueError("Resource event max_response_bytes MUST be in [1024, 5000000]")


class AzureResourceEventHistoryReader:
    """Read Resource Health history under exact server-selected Azure scope."""

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureResourceEventHistoryConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._identity: Final = identity
        self._http: Final = http_client
        self._config: Final = config
        self._now: Final = now or (lambda: datetime.now(UTC))
        self._throttle_gate = ArgThrottleGate()
        self._rate_limiter = ArgRateLimiter()

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        """Return chronological Resource Health events or an explicit limitation."""

        if event_families != RESOURCE_EVENT_MEASURE_CONCEPTS:
            raise ValueError("Azure Resource event reader received an unsupported family")
        if not 60 <= lookback_seconds <= 86_400:
            raise ValueError("Resource event lookback_seconds MUST be in [60, 86400]")
        requested = tuple(sorted(set(resource_ids)))
        observed_at = self._now()
        if observed_at.tzinfo is None:
            raise ValueError("Resource event reader clock MUST be timezone-aware")
        if (
            requested != resource_ids
            or not requested
            or len(requested) > self._config.max_resources
        ):
            raise ValueError("Resource event resource_ids MUST be ordered within the server bound")
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
                events=(),
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
                    query=_history_query(batch, lookback_seconds=lookback_seconds),
                    result_name="semantic-resource-event-history",
                    page_size=_MAX_EVENTS + 1,
                    max_pages=1,
                    max_records=_MAX_EVENTS + 1,
                    timeout_seconds=self._config.timeout_seconds,
                    error_type=ResourceEventHistoryError,
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
                events=(),
                complete=False,
                limitation="source_unavailable",
            )
        widened = False
        malformed = False
        events: list[ResourceEventObservation] = []
        for row in rows:
            target = row.get("targetResourceId")
            resource_id = (
                resource_by_arm.get(target.casefold()) if isinstance(target, str) else None
            )
            if resource_id is None:
                widened = widened or isinstance(target, str)
                malformed = malformed or not isinstance(target, str)
                continue
            event = _event(row, resource_id=resource_id)
            if event is None:
                malformed = True
                continue
            events.append(event)
        events.sort(key=lambda item: (item.occurred_at, item.evidence_ref))
        truncated = len(events) > _MAX_EVENTS
        events = events[:_MAX_EVENTS]
        limitation = (
            "provider_scope_mismatch"
            if widened
            else "resource_event_response_invalid"
            if malformed
            else "source_coverage_incomplete"
            if failed_batches
            else "result_limit"
            if truncated
            else None
        )
        return self._result(
            requested,
            observed_at=observed_at,
            events=tuple(events),
            complete=limitation is None,
            limitation=limitation,
        )

    def _result(
        self,
        resource_ids: tuple[str, ...],
        *,
        observed_at: datetime,
        events: tuple[ResourceEventObservation, ...],
        complete: bool,
        limitation: str | None,
    ) -> ResourceEventCollection:
        material = "|".join(
            (
                *resource_ids,
                observed_at.isoformat(),
                "complete" if complete else limitation or "incomplete",
            )
        )
        return ResourceEventCollection(
            resource_ids=resource_ids,
            events=events,
            observed_at=observed_at,
            complete=complete,
            limitation=limitation,
            attempt_ref=f"azure-resource-event:{hashlib.sha256(material.encode()).hexdigest()}",
        )


def _history_query(arm_ids: tuple[str, ...], *, lookback_seconds: int) -> str:
    values = ", ".join(f"'{_kusto_literal(item)}'" for item in arm_ids)
    return (
        "HealthResources "
        "| where type in~ ('microsoft.resourcehealth/availabilitystatuses', "
        "'microsoft.resourcehealth/resourceannotations') "
        f"| where tostring(properties.targetResourceId) in~ ({values}) "
        f"| where todatetime(properties.occurredTime) >= ago({lookback_seconds}s) "
        "| project targetResourceId=tostring(properties.targetResourceId), "
        "sourceType=tolower(type), "
        "availabilityState=tostring(properties.availabilityState), "
        "reasonType=tostring(properties.reasonType), "
        "annotationName=tostring(properties.annotationName), "
        "context=tostring(properties.context), "
        "reason=tostring(properties.reason), "
        "occurredTime=tostring(properties.occurredTime) "
        "| order by occurredTime asc "
        f"| take {_MAX_EVENTS + 1}"
    )


def _chunks(values: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _event(
    row: Mapping[str, Any],
    *,
    resource_id: str,
) -> ResourceEventObservation | None:
    occurred_at = _timestamp(row.get("occurredTime"))
    source_type = row.get("sourceType")
    if occurred_at is None or not isinstance(source_type, str):
        return None
    annotation = source_type.casefold().endswith("/resourceannotations")
    status_source = row.get("annotationName") if annotation else row.get("availabilityState")
    if not isinstance(status_source, str) or not status_source.strip():
        return None
    reason_source = row.get("context") or row.get("reason") if annotation else row.get("reasonType")
    classification = _classification(reason_source)
    event_kind = "resource_annotation" if annotation else "availability_status"
    status = _machine_token(status_source, fallback="unknown")
    evidence_material = (
        f"{resource_id}|{event_kind}|{status}|{classification}|{occurred_at.isoformat()}"
    )
    return ResourceEventObservation(
        resource_id=resource_id,
        event_family="resource_event.resource_health",
        event_kind=event_kind,
        status=status,
        classification=classification,
        occurred_at=occurred_at,
        evidence_ref=(
            f"azure-resource-event:{hashlib.sha256(evidence_material.encode()).hexdigest()}"
        ),
    )


def _classification(value: object) -> str:
    folded = str(value or "").casefold()
    if "customer" in folded or "user" in folded:
        return "customer_initiated"
    if "platform" in folded:
        return "platform_initiated"
    return "status_only"


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
    return normalized[:128] or fallback


def _kusto_literal(value: str) -> str:
    return value.replace("'", "''")


__all__ = [
    "AzureResourceEventHistoryConfig",
    "AzureResourceEventHistoryReader",
    "ResourceEventHistoryError",
]
