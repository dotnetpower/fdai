"""Bounded Azure source probes for the permission-aware observation campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx

from fdai.delivery.azure.log_query import AzureLogAnalyticsQueryProvider
from fdai.delivery.observation_campaign import (
    ObservationCoverage,
    ObservationProbeContractError,
    ObservationProbeResult,
    ObservationSourceSpec,
    ObservationThrottledError,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

InventoryGraphReader = Callable[..., Awaitable[Mapping[str, Any]]]

_ARG_API_VERSION = "2022-10-01"
_ACTIVITY_API_VERSION = "2015-04-01"
_COST_API_VERSION = "2023-11-01"


class AzureResourceGraphObservation(StrEnum):
    """Reviewed Azure Resource Graph query families."""

    RESOURCE_HEALTH = "resource-health"
    SERVICE_HEALTH = "service-health"
    NETWORK_CONFIG = "network-config"
    RECOVERY = "recovery"


_ARG_QUERIES: Mapping[AzureResourceGraphObservation, str] = {
    AzureResourceGraphObservation.RESOURCE_HEALTH: (
        "healthresources | where type =~ 'microsoft.resourcehealth/availabilitystatuses' "
        "| project id, properties"
    ),
    AzureResourceGraphObservation.SERVICE_HEALTH: (
        "servicehealthresources | where type =~ 'microsoft.resourcehealth/events' "
        "| project id, properties"
    ),
    AzureResourceGraphObservation.NETWORK_CONFIG: (
        "resources | where type in~ ('microsoft.network/networksecuritygroups', "
        "'microsoft.network/virtualnetworks', 'microsoft.network/routetables') "
        "| project id, type, properties"
    ),
    AzureResourceGraphObservation.RECOVERY: (
        "resources | where type in~ ('microsoft.recoveryservices/vaults', "
        "'microsoft.dataprotection/backupvaults') | project id, type, properties"
    ),
}

_LOG_QUERIES: Mapping[str, str] = {
    "logs": (
        "union isfuzzy=true "
        "(AzureActivity | summarize Count=count()), "
        "(AzureDiagnostics | summarize Count=count())"
    ),
    "guest-logs": (
        "union isfuzzy=true "
        "(Event | where EventID in (1074, 6006, 6008) | summarize Count=count()), "
        "(Syslog | where Facility in ('auth', 'authpriv', 'daemon', 'kern', 'syslog') "
        "| summarize Count=count())"
    ),
}


@dataclass(frozen=True, slots=True)
class AzureObservationConfig:
    """Configure read-only Azure management-plane observation calls."""

    subscription_ids: tuple[str, ...]
    management_endpoint: str = "https://management.azure.com"
    management_audience: str = "https://management.azure.com/.default"

    def __post_init__(self) -> None:
        if not self.subscription_ids or any(not item.strip() for item in self.subscription_ids):
            raise ValueError("Azure observation subscriptions MUST be non-empty")
        parsed = urlparse(self.management_endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Azure observation management endpoint MUST be an HTTPS origin")
        if not self.management_audience.startswith("https://"):
            raise ValueError("Azure observation management audience MUST be HTTPS")


class AzureResourceGraphObservationProbe:
    """Execute one immutable ARG query across the configured subscriptions."""

    def __init__(
        self,
        *,
        config: AzureObservationConfig,
        query: AzureResourceGraphObservation,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._query = query
        self._identity = identity
        self._http = http_client

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        token = await self._identity.get_token(self._config.management_audience)
        subscriptions, target_limited = _bounded_subscriptions(self._config, spec)
        response = await self._http.post(
            f"{self._config.management_endpoint.rstrip('/')}/providers/"
            f"Microsoft.ResourceGraph/resources?api-version={_ARG_API_VERSION}",
            headers=_headers(token.token),
            content=json.dumps(
                {
                    "subscriptions": list(subscriptions),
                    "query": f"{_ARG_QUERIES[self._query]} | take {spec.max_results + 1}",
                    "options": {"$top": spec.max_results + 1, "resultFormat": "objectArray"},
                }
            ),
            timeout=spec.timeout_seconds,
        )
        _raise_for_status(response, source=self._query.value)
        _enforce_response_size(response, spec.max_output_bytes)
        payload = _mapping(response.json(), "Resource Graph response")
        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Resource Graph response data MUST be an array")
        result_limited = len(data) > spec.max_results or bool(payload.get("skipToken"))
        reasons = tuple(
            reason
            for condition, reason in (
                (result_limited, "result_limit"),
                (target_limited, "target_limit"),
            )
            if condition
        )
        return ObservationProbeResult(
            coverage=(
                ObservationCoverage.PARTIAL
                if result_limited or target_limited
                else ObservationCoverage.READY
            ),
            evidence_count=min(len(data), spec.max_results),
            reason_codes=reasons,
        )


class AzureActivityLogObservationProbe:
    """Read bounded subscription Activity Log pages and retain only counts and cursors."""

    def __init__(
        self,
        *,
        config: AzureObservationConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        token = await self._identity.get_token(self._config.management_audience)
        count = 0
        denied = 0
        observed_bytes = 0
        try:
            cursors = _activity_cursors(cursor)
        except ValueError as exc:
            raise ObservationProbeContractError("Activity Log cursor failed validation") from exc
        subscriptions, target_limited = _bounded_subscriptions(self._config, spec)
        selected_cursor_keys = {
            _subscription_cursor_key(subscription_id) for subscription_id in subscriptions
        }
        next_cursors = {
            key: value
            for key, value in cursors.items()
            if key == "legacy" or key in selected_cursor_keys
        }
        result_limited = False
        for index, subscription_id in enumerate(subscriptions):
            source_budget = _partition_budget(
                spec.max_results,
                partitions=len(subscriptions),
                index=index,
            )
            source_count = 0
            cursor_key = _subscription_cursor_key(subscription_id)
            url = (
                f"{self._config.management_endpoint.rstrip('/')}/subscriptions/"
                f"{subscription_id}/providers/microsoft.insights/eventtypes/management/values"
            )
            lower = (
                cursors.get(cursor_key)
                or cursors.get("legacy")
                or (self._clock() - timedelta(seconds=spec.lookback_seconds)).isoformat()
            )
            checked_through = self._clock().isoformat()
            params: Mapping[str, str] | None = {
                "api-version": _ACTIVITY_API_VERSION,
                "$filter": f"eventTimestamp ge '{lower}'",
            }
            latest_timestamp: str | None = None
            complete = False
            while True:
                response = await self._http.get(
                    url,
                    params=params,
                    headers=_headers(token.token),
                    timeout=spec.timeout_seconds,
                )
                if response.status_code in {401, 403}:
                    denied += 1
                    break
                _raise_for_status(response, source="activity-log")
                observed_bytes += len(response.content)
                if observed_bytes > spec.max_output_bytes:
                    return ObservationProbeResult(
                        coverage=ObservationCoverage.PARTIAL,
                        evidence_count=count,
                        cursor=_encode_activity_cursors(next_cursors),
                        reason_codes=("byte_limit",),
                    )
                payload = _mapping(response.json(), "Activity Log response")
                values = payload.get("value")
                if not isinstance(values, list):
                    raise RuntimeError("Activity Log response value MUST be an array")
                remaining = source_budget - source_count
                if len(values) > remaining:
                    count += remaining
                    source_count += remaining
                    result_limited = True
                    break
                count += len(values)
                source_count += len(values)
                latest_timestamp = _latest_activity_timestamp(values) or latest_timestamp
                next_link = payload.get("nextLink")
                if next_link:
                    if source_count >= source_budget:
                        result_limited = True
                        break
                    url = _activity_next_link(
                        next_link,
                        management_endpoint=self._config.management_endpoint,
                        subscription_id=subscription_id,
                    )
                    params = None
                    continue
                complete = True
                break
            if response.status_code in {401, 403}:
                continue
            if not complete:
                continue
            next_cursors[cursor_key] = latest_timestamp or checked_through
        if denied == len(subscriptions) and not target_limited:
            raise PermissionError("Activity Log access denied")
        if denied or target_limited or result_limited:
            reasons = tuple(
                reason
                for condition, reason in (
                    (denied > 0, "source_unauthorized"),
                    (target_limited, "target_limit"),
                    (result_limited, "result_limit"),
                )
                if condition
            )
            return ObservationProbeResult(
                coverage=ObservationCoverage.PARTIAL,
                evidence_count=count,
                cursor=_encode_activity_cursors(next_cursors),
                reason_codes=reasons,
            )
        return ObservationProbeResult(
            coverage=ObservationCoverage.READY,
            evidence_count=count,
            cursor=_encode_activity_cursors(next_cursors),
        )


class AzureCostObservationProbe:
    """Read one bounded daily Cost Management aggregate per subscription."""

    def __init__(
        self,
        *,
        config: AzureObservationConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        token = await self._identity.get_token(self._config.management_audience)
        count = 0
        denied = 0
        observed_bytes = 0
        subscriptions, target_limited = _bounded_subscriptions(self._config, spec)
        body = {
            "type": "ActualCost",
            "timeframe": "MonthToDate",
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            },
        }
        for subscription_id in subscriptions:
            response = await self._http.post(
                f"{self._config.management_endpoint.rstrip('/')}/subscriptions/"
                f"{subscription_id}/providers/Microsoft.CostManagement/query"
                f"?api-version={_COST_API_VERSION}",
                headers=_headers(token.token),
                content=json.dumps(body),
                timeout=spec.timeout_seconds,
            )
            if response.status_code in {401, 403}:
                denied += 1
                continue
            _raise_for_status(response, source="cost")
            observed_bytes += len(response.content)
            if observed_bytes > spec.max_output_bytes:
                return ObservationProbeResult(
                    coverage=ObservationCoverage.PARTIAL,
                    evidence_count=min(count, spec.max_results),
                    reason_codes=("byte_limit",),
                )
            payload = _mapping(response.json(), "Cost Management response")
            properties = _mapping(payload.get("properties"), "Cost Management properties")
            rows = properties.get("rows")
            if not isinstance(rows, list):
                raise RuntimeError("Cost Management rows MUST be an array")
            count += len(rows)
        if denied == len(subscriptions) and not target_limited:
            raise PermissionError("Cost Management access denied")
        if denied or target_limited:
            reasons = tuple(
                reason
                for condition, reason in (
                    (denied > 0, "source_unauthorized"),
                    (target_limited, "target_limit"),
                    (count > spec.max_results, "result_limit"),
                )
                if condition
            )
            return ObservationProbeResult(
                coverage=ObservationCoverage.PARTIAL,
                evidence_count=min(count, spec.max_results),
                reason_codes=reasons,
            )
        truncated = count > spec.max_results
        return ObservationProbeResult(
            coverage=(ObservationCoverage.PARTIAL if truncated else ObservationCoverage.READY),
            evidence_count=min(count, spec.max_results),
            reason_codes=(("result_limit",) if truncated else ()),
        )


class AzureLogAnalyticsObservationProbe:
    """Run one reviewed Log Analytics coverage query without retaining rows."""

    def __init__(self, provider: AzureLogAnalyticsQueryProvider, *, source_id: str) -> None:
        try:
            self._query = _LOG_QUERIES[source_id]
        except KeyError as exc:
            raise ValueError("Log Analytics observation source is unsupported") from exc
        self._provider = provider

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        result = await self._provider.query_log(
            query=self._query,
            window=f"PT{spec.lookback_seconds}S",
            max_rows=spec.max_results,
        )
        scanned_records = (
            result.scanned_records if result.scanned_records is not None else len(result.rows)
        )
        return ObservationProbeResult(
            coverage=(
                ObservationCoverage.PARTIAL if result.truncated else ObservationCoverage.READY
            ),
            evidence_count=min(scanned_records, spec.max_results),
            reason_codes=(("result_limit",) if result.truncated else ()),
        )


class PromotedInventoryObservationProbe:
    """Verify the promoted PostgreSQL graph without starting another scan."""

    def __init__(self, graph_reader: InventoryGraphReader) -> None:
        self._graph_reader = graph_reader

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult:
        del cursor
        graph = await self._graph_reader(None, 1, (), limit=spec.max_results)
        resources = graph.get("resources")
        links = graph.get("links")
        if not isinstance(resources, Sequence) or isinstance(resources, (str, bytes)):
            raise RuntimeError("promoted inventory resources MUST be an array")
        if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
            raise RuntimeError("promoted inventory links MUST be an array")
        count = len(resources) + len(links)
        if graph.get("source") == "unavailable":
            return ObservationProbeResult(
                coverage=ObservationCoverage.UNCONFIGURED,
                reason_codes=("source_unconfigured",),
            )
        if graph.get("freshness") == "stale":
            return ObservationProbeResult(
                coverage=ObservationCoverage.STALE,
                evidence_count=min(count, spec.max_results),
                reason_codes=("source_stale",),
            )
        truncated = bool(graph.get("truncated")) or count > spec.max_results
        return ObservationProbeResult(
            coverage=(ObservationCoverage.PARTIAL if truncated else ObservationCoverage.READY),
            evidence_count=min(count, spec.max_results),
            reason_codes=(("result_limit",) if truncated else ()),
        )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _bounded_subscriptions(
    config: AzureObservationConfig,
    spec: ObservationSourceSpec,
) -> tuple[tuple[str, ...], bool]:
    subscriptions = config.subscription_ids[: spec.max_targets]
    return subscriptions, len(subscriptions) < len(config.subscription_ids)


def _partition_budget(total: int, *, partitions: int, index: int) -> int:
    quotient, remainder = divmod(total, partitions)
    return quotient + (1 if index < remainder else 0)


def _raise_for_status(response: httpx.Response, *, source: str) -> None:
    if response.status_code in {401, 403}:
        raise PermissionError(f"{source} access denied")
    if response.status_code == 429:
        raise ObservationThrottledError(f"{source} throttled")
    if response.status_code >= 400:
        raise RuntimeError(f"{source} returned HTTP {response.status_code}")


def _enforce_response_size(response: httpx.Response, maximum: int) -> None:
    if len(response.content) > maximum:
        raise RuntimeError("Azure observation response exceeded its byte limit")


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{field} MUST be an object")
    return value


def _latest_activity_timestamp(values: Sequence[object]) -> str | None:
    timestamps: list[str] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        timestamp = value.get("eventTimestamp")
        if isinstance(timestamp, str):
            timestamps.append(timestamp)
    return max(timestamps) if timestamps else None


def _activity_cursors(cursor: str | None) -> dict[str, str]:
    if cursor is None:
        return {}
    try:
        payload = json.loads(cursor)
    except json.JSONDecodeError:
        _validate_activity_timestamp(cursor)
        return {"legacy": cursor}
    if not isinstance(payload, Mapping) or payload.get("version") != 1:
        raise ValueError("Activity Log cursor is unsupported")
    values = payload.get("subscriptions")
    if not isinstance(values, Mapping) or len(values) > 100:
        raise ValueError("Activity Log cursor subscriptions MUST be bounded")
    parsed: dict[str, str] = {}
    for key, value in values.items():
        if (
            not isinstance(key, str)
            or not key.startswith("sha256:")
            or len(key) != 71
            or not isinstance(value, str)
            or len(value) > 64
        ):
            raise ValueError("Activity Log cursor entry is invalid")
        _validate_activity_timestamp(value)
        parsed[key] = value
    return parsed


def _encode_activity_cursors(cursors: Mapping[str, str]) -> str | None:
    persisted = {key: value for key, value in cursors.items() if key != "legacy"}
    if not persisted:
        return None
    encoded = json.dumps(
        {"subscriptions": persisted, "version": 1},
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded) > 4096:
        return min(persisted.values())
    return encoded


def _subscription_cursor_key(subscription_id: str) -> str:
    return f"sha256:{hashlib.sha256(subscription_id.encode()).hexdigest()}"


def _activity_next_link(
    value: object,
    *,
    management_endpoint: str,
    subscription_id: str,
) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise RuntimeError("Activity Log nextLink MUST be bounded text")
    parsed = urlparse(value)
    management = urlparse(management_endpoint)
    if parsed.scheme != "https" or parsed.netloc.lower() != management.netloc.lower():
        raise RuntimeError("Activity Log nextLink MUST stay on the management endpoint")
    subscription_prefix = f"/subscriptions/{subscription_id.lower()}/"
    if not parsed.path.lower().startswith(subscription_prefix):
        raise RuntimeError("Activity Log nextLink MUST stay within its subscription")
    return value


def _validate_activity_timestamp(value: str) -> None:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Activity Log cursor timestamp is invalid") from exc
    if timestamp.tzinfo is None:
        raise ValueError("Activity Log cursor timestamp MUST include a timezone")


__all__ = [
    "AzureActivityLogObservationProbe",
    "AzureCostObservationProbe",
    "AzureLogAnalyticsObservationProbe",
    "AzureObservationConfig",
    "AzureResourceGraphObservation",
    "AzureResourceGraphObservationProbe",
    "PromotedInventoryObservationProbe",
]
