"""Bounded Azure Activity Log evidence for exact read-investigation targets."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import httpx

from fdai.delivery.azure.metric_window import azure_arm_resource_id
from fdai.shared.providers.read_investigation import (
    ActorKind,
    EvidenceFreshness,
    EvidenceLimitationKind,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationProvider,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
    ResourceResolutionAttempt,
    ResourceSelector,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_ORIGIN = "https://management.azure.com"
_MANAGEMENT_AUDIENCE = "https://management.azure.com/.default"
_ACTIVITY_API_VERSION = "2015-04-01"
_RESOURCE_HEALTH_API_VERSION = "2025-05-01"


@dataclass(frozen=True, slots=True)
class AzureActivityReadConfig:
    """Server-owned scope and deadline for one bounded Activity Log page."""

    subscription_id: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.subscription_id))
        except (AttributeError, ValueError) as exc:
            raise ValueError("subscription_id MUST be a canonical UUID") from exc
        if canonical != self.subscription_id.casefold():
            raise ValueError("subscription_id MUST be a canonical UUID")
        if not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds MUST be in [0.1, 30]")


class AzureActivityReadInvestigationProvider:
    """Add exact-target Activity Log reads to an inventory-backed provider."""

    transport = "azure_activity_log"

    def __init__(
        self,
        *,
        base: ReadInvestigationProvider,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureActivityReadConfig,
    ) -> None:
        self._base: Final = base
        self._identity: Final = identity
        self._http: Final = http_client
        self._config: Final = config

    async def resolve_resource(
        self,
        selector: ResourceSelector,
        *,
        limits: ReadToolLimits,
    ) -> ResourceResolutionAttempt:
        return await self._base.resolve_resource(selector, limits=limits)

    async def get_resource_state(
        self,
        resource: ResolvedResource,
        *,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        return await self._base.get_resource_state(resource, limits=limits)

    async def query_resource_activity(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        started = time.monotonic()
        observed_at = datetime.now(UTC)
        if resource.resource_group is None:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail="exact resource group is unavailable",
            )
        lower = observed_at - timedelta(seconds=lookback_seconds)
        endpoint = (
            f"{_MANAGEMENT_ORIGIN}/subscriptions/{self._config.subscription_id}/"
            "providers/Microsoft.Insights/eventtypes/management/values"
        )
        filter_value = (
            f"eventTimestamp ge '{_azure_time(lower)}' and "
            f"eventTimestamp le '{_azure_time(observed_at)}' and "
            f"resourceGroupName eq '{_odata_literal(resource.resource_group)}'"
        )
        try:
            token = await self._identity.get_token(_MANAGEMENT_AUDIENCE)
            response = await self._http.get(
                endpoint,
                params={"api-version": _ACTIVITY_API_VERSION, "$filter": filter_value},
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=min(self._config.timeout_seconds, limits.timeout_seconds),
            )
        except (httpx.HTTPError, TimeoutError):
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail="Activity Log transport unavailable",
            )
        if response.status_code in {401, 403}:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.UNAUTHORIZED,
                detail="Activity Log authorization unavailable",
            )
        if response.status_code != 200:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail=f"Activity Log returned HTTP {response.status_code}",
            )
        if len(response.content) > limits.max_output_bytes:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.BYTE_LIMIT,
                detail="Activity Log response exceeded the byte limit",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail="Activity Log response shape unavailable",
            )
        matched = [
            record
            for item in payload["value"]
            if isinstance(item, dict)
            and (
                record := _activity_record(
                    item,
                    resource=resource,
                    subscription_id=self._config.subscription_id,
                )
            )
            is not None
        ]
        matched.sort(key=lambda item: item.occurred_at)
        truncated = len(matched) > limits.max_results or isinstance(payload.get("nextLink"), str)
        records = tuple(matched[-limits.max_results :])
        limitations = (EvidenceLimitationKind.RESULT_LIMIT,) if truncated else ()
        evidence_refs = tuple(
            _activity_evidence_ref(record, resource_ref=resource.resource_ref) for record in records
        )
        evidence = ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED if records else EvidenceStatus.NONE,
            authority="azure.activity_log",
            resource_ref=resource.resource_ref,
            observed_at=observed_at,
            freshness=EvidenceFreshness.LIVE,
            truncated=truncated,
            records=records,
            evidence_refs=evidence_refs,
            limitations=limitations,
            truncation_reason=(EvidenceLimitationKind.RESULT_LIMIT if truncated else None),
        )
        return ReadEvidenceAttempt(
            tool_id=ReadToolId.QUERY_RESOURCE_ACTIVITY,
            evidence=evidence,
            receipt=_receipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                detail="bounded Activity Log read completed",
                started=started,
                result_count=len(records),
                truncated=truncated,
                recorded_at=observed_at,
            ),
        )

    async def query_resource_health(
        self,
        resource: ResolvedResource,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> ReadEvidenceAttempt:
        """Read current Resource Health for one already scope-resolved target."""

        del lookback_seconds
        started = time.monotonic()
        observed_at = datetime.now(UTC)
        try:
            resource_id = azure_arm_resource_id(
                resource.resource_ref,
                subscription_id=self._config.subscription_id,
            )
        except ValueError:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail="exact Resource Health target is unavailable",
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                authority="azure.resource_health",
            )
        endpoint = (
            f"{_MANAGEMENT_ORIGIN}{resource_id}/providers/"
            "Microsoft.ResourceHealth/availabilityStatuses/current"
        )
        try:
            token = await self._identity.get_token(_MANAGEMENT_AUDIENCE)
            response = await self._http.get(
                endpoint,
                params={"api-version": _RESOURCE_HEALTH_API_VERSION},
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=min(self._config.timeout_seconds, limits.timeout_seconds),
            )
        except (httpx.HTTPError, TimeoutError):
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail="Resource Health transport unavailable",
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                authority="azure.resource_health",
            )
        if response.status_code in {401, 403}:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.UNAUTHORIZED,
                detail="Resource Health authorization unavailable",
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                authority="azure.resource_health",
            )
        if response.status_code != 200:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail=f"Resource Health returned HTTP {response.status_code}",
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                authority="azure.resource_health",
            )
        if len(response.content) > limits.max_output_bytes:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.BYTE_LIMIT,
                detail="Resource Health response exceeded the byte limit",
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                authority="azure.resource_health",
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        record = _resource_health_record(payload, observed_at=observed_at)
        if record is None:
            return self._unavailable(
                resource,
                observed_at=observed_at,
                started=started,
                limitation=EvidenceLimitationKind.SOURCE_UNAVAILABLE,
                detail="Resource Health response shape unavailable",
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                authority="azure.resource_health",
            )
        evidence = ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED,
            authority="azure.resource_health",
            resource_ref=resource.resource_ref,
            observed_at=observed_at,
            freshness=EvidenceFreshness.LIVE,
            truncated=False,
            records=(record,),
            evidence_refs=(
                _resource_health_evidence_ref(record, resource_ref=resource.resource_ref),
            ),
        )
        return ReadEvidenceAttempt(
            tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
            evidence=evidence,
            receipt=_receipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                detail="bounded Resource Health read completed",
                started=started,
                result_count=1,
                recorded_at=observed_at,
                tool_id=ReadToolId.QUERY_RESOURCE_HEALTH,
                operation_class="resource_health",
            ),
        )

    async def query_guest_shutdown_events(self, resource, *, lookback_seconds, limits):  # type: ignore[no-untyped-def]
        return await self._base.query_guest_shutdown_events(
            resource,
            lookback_seconds=lookback_seconds,
            limits=limits,
        )

    async def query_network_security(self, resource, *, limits):  # type: ignore[no-untyped-def]
        return await self._base.query_network_security(resource, limits=limits)

    async def query_network_peerings(self, resource, *, limits):  # type: ignore[no-untyped-def]
        return await self._base.query_network_peerings(resource, limits=limits)

    def _unavailable(
        self,
        resource: ResolvedResource,
        *,
        observed_at: datetime,
        started: float,
        limitation: EvidenceLimitationKind,
        detail: str,
        tool_id: ReadToolId = ReadToolId.QUERY_RESOURCE_ACTIVITY,
        authority: str = "azure.activity_log",
    ) -> ReadEvidenceAttempt:
        return ReadEvidenceAttempt(
            tool_id=tool_id,
            evidence=ReadEvidenceEnvelope(
                status=EvidenceStatus.UNAVAILABLE,
                authority=authority,
                resource_ref=resource.resource_ref,
                observed_at=observed_at,
                freshness=EvidenceFreshness.LIVE,
                truncated=False,
                records=(),
                evidence_refs=(),
                limitations=(limitation,),
            ),
            receipt=_receipt(
                outcome=ToolCallOutcome.FAILED,
                detail=detail,
                started=started,
                recorded_at=observed_at,
                tool_id=tool_id,
                operation_class=(
                    "resource_health"
                    if tool_id is ReadToolId.QUERY_RESOURCE_HEALTH
                    else "control_plane_activity"
                ),
            ),
        )


def _activity_record(
    raw: dict[str, object],
    *,
    resource: ResolvedResource,
    subscription_id: str,
) -> ReadEvidenceRecord | None:
    resource_id = raw.get("resourceId")
    if not isinstance(resource_id, str) or not _resource_id_matches(
        resource_id,
        resource=resource,
        subscription_id=subscription_id,
    ):
        return None
    occurred_at = _timestamp(raw.get("eventTimestamp"))
    operation = _event_value(raw.get("operationName"))
    status = _event_value(raw.get("status"))
    if occurred_at is None or operation is None or status is None:
        return None
    caller = raw.get("caller")
    correlation = raw.get("correlationId")
    return ReadEvidenceRecord(
        occurred_at=occurred_at,
        status=_machine_token(status),
        operation_kind=_machine_token(operation),
        actor_ref=(caller if isinstance(caller, str) and caller.strip() else None),
        actor_kind=(_actor_kind(caller) if isinstance(caller, str) and caller.strip() else None),
        correlation_ref=(
            correlation if isinstance(correlation, str) and correlation.strip() else None
        ),
    )


def _resource_health_record(
    raw: object,
    *,
    observed_at: datetime,
) -> ReadEvidenceRecord | None:
    if not isinstance(raw, Mapping):
        return None
    properties = raw.get("properties")
    if not isinstance(properties, Mapping):
        return None
    availability = properties.get("availabilityState")
    if not isinstance(availability, str) or not availability.strip():
        return None
    reason = properties.get("reasonType")
    reported_at = _timestamp(properties.get("reportedTime"))
    occurred_at = reported_at or _timestamp(properties.get("occurredTime")) or observed_at
    return ReadEvidenceRecord(
        occurred_at=occurred_at,
        status=_machine_token(availability),
        state=_machine_token(availability),
        health_kind=_health_kind(reason),
    )


def _health_kind(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "status_only"
    normalized = _machine_token(value)
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


def _resource_id_matches(
    resource_id: str,
    *,
    resource: ResolvedResource,
    subscription_id: str,
) -> bool:
    folded = resource_id.casefold().rstrip("/")
    try:
        expected = azure_arm_resource_id(
            resource.resource_ref,
            subscription_id=subscription_id,
        )
    except ValueError:
        return False
    return folded == expected


def _event_value(value: object) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("value")
        return candidate if isinstance(candidate, str) and candidate.strip() else None
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _machine_token(value: str) -> str:
    normalized = "".join(character if character.isalnum() else "_" for character in value)
    return normalized.strip("_").casefold()[:256] or "unknown"


def _actor_kind(value: str) -> ActorKind:
    folded = value.casefold()
    if "@" in value:
        return ActorKind.USER
    if "managedidentity" in folded or "managed_identity" in folded:
        return ActorKind.MANAGED_IDENTITY
    return ActorKind.SERVICE_PRINCIPAL


def _activity_evidence_ref(record: ReadEvidenceRecord, *, resource_ref: str) -> str:
    material = (
        f"{resource_ref}|{record.occurred_at.isoformat()}|{record.operation_kind}|"
        f"{record.status}|{record.correlation_ref or ''}"
    )
    return f"azure-activity:{hashlib.sha256(material.encode()).hexdigest()}"


def _resource_health_evidence_ref(
    record: ReadEvidenceRecord,
    *,
    resource_ref: str,
) -> str:
    material = (
        f"{resource_ref}|{record.occurred_at.isoformat()}|{record.state}|{record.health_kind}"
    )
    return f"azure-resource-health:{hashlib.sha256(material.encode()).hexdigest()}"


def _receipt(
    *,
    outcome: ToolCallOutcome,
    detail: str,
    started: float,
    recorded_at: datetime,
    result_count: int = 0,
    truncated: bool = False,
    tool_id: ReadToolId = ReadToolId.QUERY_RESOURCE_ACTIVITY,
    operation_class: str = "control_plane_activity",
) -> ToolCallReceipt:
    digest = hashlib.sha256(
        f"{recorded_at.isoformat()}|{detail}|{result_count}".encode()
    ).hexdigest()
    return ToolCallReceipt(
        outcome=outcome,
        receipt_ref=f"azure-read:{digest}",
        detail=detail,
        tool_id=tool_id.value,
        transport="azure_rest",
        operation_class=operation_class,
        execution_duration_ms=max(0, round((time.monotonic() - started) * 1_000)),
        result_count=result_count,
        truncated=truncated,
        recorded_at=recorded_at,
    )


def _azure_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _odata_literal(value: str) -> str:
    return value.replace("'", "''")


__all__ = ["AzureActivityReadConfig", "AzureActivityReadInvestigationProvider"]
