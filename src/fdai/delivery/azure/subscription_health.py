"""Bounded Azure subscription-scope health and metric sweep."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any, Final
from urllib.parse import quote

import httpx

from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_ARG_API_VERSION: Final = "2022-10-01"
_METRICS_API_VERSION: Final = "2024-02-01"
_RESOURCE_HEALTH_API_VERSION: Final = "2025-05-01"
_SUBSCRIPTIONS_API_VERSION: Final = "2022-12-01"
_RESOURCE_HEALTH_ID_MARKER: Final = "/providers/microsoft.resourcehealth/availabilitystatuses/"


class AzureSubscriptionHealthScope(StrEnum):
    RESOURCE_GROUPS = "resource_groups"
    SUBSCRIPTION = "subscription"


@dataclass(frozen=True, slots=True)
class MetricProbeSpec:
    resource_type: str
    metric_name: str
    aggregation: str
    comparison: str
    threshold: float

    def __post_init__(self) -> None:
        if self.comparison not in {"gt", "lt"}:
            raise ValueError("metric comparison MUST be gt or lt")
        if self.aggregation not in {"Average", "Maximum", "Minimum"}:
            raise ValueError("metric aggregation is unsupported")
        if not isfinite(self.threshold):
            raise ValueError("metric threshold MUST be finite")


DEFAULT_METRIC_PROBES: Final[tuple[MetricProbeSpec, ...]] = (
    MetricProbeSpec("microsoft.compute/virtualmachines", "Percentage CPU", "Maximum", "gt", 90.0),
    MetricProbeSpec(
        "microsoft.containerservice/managedclusters",
        "node_cpu_usage_percentage",
        "Maximum",
        "gt",
        90.0,
    ),
    MetricProbeSpec("microsoft.storage/storageaccounts", "Availability", "Average", "lt", 99.0),
    MetricProbeSpec(
        "microsoft.dbforpostgresql/flexibleservers",
        "cpu_percent",
        "Maximum",
        "gt",
        90.0,
    ),
    MetricProbeSpec(
        "microsoft.dbformysql/flexibleservers",
        "cpu_percent",
        "Maximum",
        "gt",
        90.0,
    ),
    MetricProbeSpec("microsoft.sql/servers/databases", "cpu_percent", "Maximum", "gt", 90.0),
    MetricProbeSpec(
        "microsoft.network/applicationgateways",
        "HealthyHostCount",
        "Minimum",
        "lt",
        1.0,
    ),
)


@dataclass(frozen=True, slots=True)
class AzureSubscriptionHealthConfig:
    subscription_id: str
    resource_groups: tuple[str, ...]
    scope: AzureSubscriptionHealthScope = AzureSubscriptionHealthScope.RESOURCE_GROUPS
    endpoint: str = "https://management.azure.com"
    max_resources: int = 256
    max_metric_resources: int = 16
    max_concurrent_queries: int = 4
    timeout_seconds: float = 30.0
    max_response_bytes: int = 5_000_000
    metric_probes: tuple[MetricProbeSpec, ...] = DEFAULT_METRIC_PROBES

    def __post_init__(self) -> None:
        if not self.subscription_id.strip():
            raise ValueError("subscription health requires a subscription")
        if self.scope is AzureSubscriptionHealthScope.RESOURCE_GROUPS and not self.resource_groups:
            raise ValueError("resource-group health scope requires resource groups")
        if len(self.resource_groups) > 64:
            raise ValueError("subscription health supports at most 64 resource groups")
        if not self.endpoint.startswith("https://"):
            raise ValueError("subscription health endpoint MUST use https")
        if not 1 <= self.max_resources <= 1_000:
            raise ValueError("max_resources MUST be in [1, 1000]")
        if not 1 <= self.max_metric_resources <= 64:
            raise ValueError("max_metric_resources MUST be in [1, 64]")
        if not 1 <= self.max_concurrent_queries <= 8:
            raise ValueError("max_concurrent_queries MUST be in [1, 8]")
        if not 0.1 <= self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds MUST be in [0.1, 120]")


class AzureSubscriptionHealthProvider:
    """Inspect the configured Azure reader scope without accepting caller scope."""

    def __init__(
        self,
        *,
        config: AzureSubscriptionHealthConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client
        self._probe_by_type = {probe.resource_type: probe for probe in config.metric_probes}

    @property
    def scope(self) -> AzureSubscriptionHealthScope:
        """Return the immutable server-owned scope mode."""

        return self._config.scope

    async def describe_scope(self) -> dict[str, Any]:
        """Return normalized metadata for the configured subscription scope."""

        token = await self._identity.get_token(_MANAGEMENT_AUDIENCE)
        response = await self._http.get(
            f"{self._config.endpoint.rstrip('/')}/subscriptions/"
            f"{quote(self._config.subscription_id, safe='')}",
            params={"api-version": _SUBSCRIPTIONS_API_VERSION},
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=self._config.timeout_seconds,
        )
        if response.status_code >= 400 or len(response.content) > self._config.max_response_bytes:
            raise RuntimeError("Azure subscription metadata query unavailable")
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise RuntimeError("Azure subscription metadata response is invalid")
        subscription_id = payload.get("subscriptionId")
        display_name = payload.get("displayName")
        state = payload.get("state")
        if (
            not isinstance(subscription_id, str)
            or subscription_id.casefold() != self._config.subscription_id.casefold()
            or not isinstance(display_name, str)
            or not display_name.strip()
            or not isinstance(state, str)
            or not state.strip()
        ):
            raise RuntimeError("Azure subscription metadata response is incomplete")
        return {
            "status": "matched",
            "source": "azure-resource-manager",
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "display_name": display_name.strip(),
            "subscription_id": subscription_id,
            "state": state.strip(),
        }

    async def __call__(
        self,
        lookback_seconds: int,
        *,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        if not 60 <= lookback_seconds <= 86_400:
            raise ValueError("subscription health lookback MUST be in [60, 86400]")
        token = await self._identity.get_token(_MANAGEMENT_AUDIENCE)
        headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}
        await _emit(
            progress_observer,
            kind="inventory.querying",
            status="running",
            label="Discovering resources",
        )
        await _emit(
            progress_observer,
            kind="resource-health.querying",
            status="running",
            label="Checking Resource Health",
        )
        resources, health = await asyncio.gather(
            self._arg(headers, self._resource_query()),
            self._arg(headers, self._health_query()),
        )
        safe_resources = [item for item in resources if _valid_resource(item)]
        resource_truncated = len(safe_resources) > self._config.max_resources
        safe_resources = safe_resources[: self._config.max_resources]
        resource_health_unavailable = 0
        direct_health_truncated = False
        if not health:
            (
                health,
                resource_health_unavailable,
                direct_health_truncated,
            ) = await self._current_resource_health(headers)
        health_findings = _health_findings(health)
        provisioning_findings = _provisioning_findings(safe_resources)
        health_truncated = len(health) > 64 or direct_health_truncated
        await _emit(
            progress_observer,
            kind="inventory.completed",
            status="completed",
            label="Resource discovery completed",
            completed=len(safe_resources),
            total=len(safe_resources),
        )
        await _emit(
            progress_observer,
            kind="resource-health.completed",
            status="completed",
            label="Resource Health checked",
            completed=min(len(health), 64),
            total=min(len(health), 64),
        )
        supported = [
            item
            for item in safe_resources
            if str(item.get("type", "")).casefold() in self._probe_by_type
        ]
        metric_truncated = len(supported) > self._config.max_metric_resources
        metric_targets = supported[: self._config.max_metric_resources]
        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        async def inspect(resource: Mapping[str, Any]) -> dict[str, Any]:
            async with semaphore:
                probe = self._probe_by_type[str(resource["type"]).casefold()]
                return await self._metric(headers, resource, probe, lookback_seconds)

        await _emit(
            progress_observer,
            kind="metrics.querying",
            status="running",
            label="Checking representative metrics",
            completed=0,
            total=len(metric_targets),
        )
        metric_tasks = [asyncio.create_task(inspect(resource)) for resource in metric_targets]
        metric_findings: list[dict[str, Any]] = []
        metric_unavailable = 0
        metric_completed = 0
        try:
            for task in asyncio.as_completed(metric_tasks):
                try:
                    result = await task
                except Exception:  # noqa: BLE001 - one failure produces partial evidence
                    metric_unavailable += 1
                else:
                    if result.get("anomalous") is True:
                        metric_findings.append(result)
                metric_completed += 1
                await _emit(
                    progress_observer,
                    kind="metrics.querying",
                    status="running",
                    label="Checking representative metrics",
                    completed=metric_completed,
                    total=len(metric_targets),
                )
        finally:
            for metric_task in metric_tasks:
                if not metric_task.done():
                    metric_task.cancel()
            await asyncio.gather(*metric_tasks, return_exceptions=True)
        await _emit(
            progress_observer,
            kind="metrics.completed",
            status="unavailable" if metric_unavailable else "completed",
            label="Representative metrics checked",
            completed=metric_completed - metric_unavailable,
            total=len(metric_targets),
        )
        findings = [*health_findings, *provisioning_findings, *metric_findings]
        unsupported_metric_resources = len(safe_resources) - len(supported)
        truncated = resource_truncated or health_truncated or metric_truncated
        await _emit(
            progress_observer,
            kind="evidence.correlating",
            status="running",
            label="Correlating health evidence",
        )
        return {
            "status": (
                "partial"
                if (
                    resource_health_unavailable
                    or metric_unavailable
                    or unsupported_metric_resources
                    or truncated
                )
                else "matched"
            ),
            "source": "azure-resource-graph+resource-health+azure-monitor-metrics",
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "resource_count": len(safe_resources),
            "resource_health_unavailable": resource_health_unavailable,
            "supported_metric_resources": len(supported),
            "metric_checked": len(metric_targets) - metric_unavailable,
            "metric_unavailable": metric_unavailable,
            "unsupported_metric_resources": unsupported_metric_resources,
            "truncated": truncated,
            "findings": findings[:64],
        }

    async def _current_resource_health(
        self,
        headers: Mapping[str, str],
    ) -> tuple[list[Mapping[str, Any]], int, bool]:
        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        async def inspect(group: str | None) -> tuple[list[Mapping[str, Any]], bool]:
            async with semaphore:
                scope_path = "" if group is None else f"/resourceGroups/{quote(group, safe='')}"
                response = await self._http.get(
                    f"{self._config.endpoint.rstrip('/')}/subscriptions/"
                    f"{quote(self._config.subscription_id, safe='')}{scope_path}/providers/"
                    "Microsoft.ResourceHealth/availabilityStatuses",
                    params={"api-version": _RESOURCE_HEALTH_API_VERSION},
                    headers=dict(headers),
                    timeout=self._config.timeout_seconds,
                )
                scope_prefix = f"/subscriptions/{self._config.subscription_id.casefold()}/"
                if group is not None:
                    scope_prefix += f"resourcegroups/{group.casefold()}/"
                return self._resource_health_rows(response, scope_prefix)

        targets: tuple[str | None, ...] = (
            (None,)
            if self._config.scope is AzureSubscriptionHealthScope.SUBSCRIPTION
            else self._config.resource_groups
        )
        results = await asyncio.gather(
            *(inspect(group) for group in targets),
            return_exceptions=True,
        )
        rows: list[Mapping[str, Any]] = []
        unavailable = 0
        truncated = False
        for result in results:
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                unavailable += 1
                continue
            group_rows, group_truncated = result
            rows.extend(group_rows)
            truncated = truncated or group_truncated
        return rows[:65], unavailable, truncated or len(rows) > 65

    def _resource_health_rows(
        self,
        response: httpx.Response,
        scope_prefix: str,
    ) -> tuple[list[Mapping[str, Any]], bool]:
        if response.status_code >= 400 or len(response.content) > self._config.max_response_bytes:
            raise RuntimeError("Resource Health query unavailable")
        payload = response.json()
        values = payload.get("value") if isinstance(payload, Mapping) else None
        if not isinstance(values, list):
            raise RuntimeError("Resource Health response is invalid")
        rows: list[Mapping[str, Any]] = []
        for value in values:
            if not isinstance(value, Mapping):
                continue
            status_id = value.get("id")
            properties = value.get("properties")
            if not isinstance(status_id, str) or not isinstance(properties, Mapping):
                continue
            marker_at = status_id.casefold().find(_RESOURCE_HEALTH_ID_MARKER)
            target_resource_id = status_id[:marker_at] if marker_at >= 0 else ""
            if not target_resource_id.casefold().startswith(scope_prefix):
                continue
            rows.append(
                {
                    "targetResourceId": target_resource_id,
                    "resourceName": target_resource_id.rsplit("/", maxsplit=1)[-1],
                    "availabilityState": properties.get("availabilityState"),
                    "reasonType": properties.get("reasonType"),
                    "title": properties.get("title"),
                    "occurredTime": properties.get("occurredTime")
                    or properties.get("reportedTime"),
                }
            )
        return rows[:65], isinstance(payload.get("nextLink"), str) or len(rows) > 65

    async def _arg(self, headers: Mapping[str, str], query: str) -> list[Mapping[str, Any]]:
        response = await self._http.post(
            f"{self._config.endpoint.rstrip('/')}/providers/Microsoft.ResourceGraph/resources",
            params={"api-version": _ARG_API_VERSION},
            headers=dict(headers),
            json={"subscriptions": [self._config.subscription_id], "query": query},
            timeout=self._config.timeout_seconds,
        )
        return self._rows(response, "Resource Graph")

    async def _metric(
        self,
        headers: Mapping[str, str],
        resource: Mapping[str, Any],
        probe: MetricProbeSpec,
        lookback_seconds: int,
    ) -> dict[str, Any]:
        resource_id = str(resource["id"])
        until = datetime.now(tz=UTC)
        since = until - timedelta(seconds=lookback_seconds)
        response = await self._http.get(
            f"{self._config.endpoint.rstrip('/')}{quote(resource_id, safe='/')}"
            "/providers/Microsoft.Insights/metrics",
            params={
                "api-version": _METRICS_API_VERSION,
                "metricnames": probe.metric_name,
                "aggregation": probe.aggregation,
                "interval": "PT5M",
                "timespan": f"{since.isoformat()}/{until.isoformat()}",
            },
            headers=dict(headers),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code >= 400 or len(response.content) > self._config.max_response_bytes:
            raise RuntimeError("Azure Monitor metric query unavailable")
        value = _metric_value(response.json(), probe.aggregation.casefold())
        anomalous = value > probe.threshold if probe.comparison == "gt" else value < probe.threshold
        return {
            "kind": "metric",
            "resource_name": resource["name"],
            "resource_type": resource["type"],
            "resource_group": resource["resourceGroup"],
            "status": "anomalous" if anomalous else "observed",
            "metric": probe.metric_name,
            "value": value,
            "threshold": probe.threshold,
            "comparison": probe.comparison,
            "anomalous": anomalous,
        }

    def _rows(self, response: httpx.Response, source: str) -> list[Mapping[str, Any]]:
        if response.status_code >= 400 or len(response.content) > self._config.max_response_bytes:
            raise RuntimeError(f"{source} query unavailable")
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"{source} response is invalid")
        return [row for row in rows if isinstance(row, Mapping)]

    def _scope_filter(self, field: str) -> str | None:
        if self._config.scope is AzureSubscriptionHealthScope.SUBSCRIPTION:
            return None
        values = ", ".join(f"'{_escaped(group)}'" for group in self._config.resource_groups)
        return f"{field} in~ ({values})"

    def _resource_query(self) -> str:
        scope_filter = self._scope_filter("resourceGroup")
        where = f"| where {scope_filter} " if scope_filter is not None else ""
        return (
            f"Resources {where}"
            "| project id, name, type, resourceGroup, location, "
            "provisioningState=tostring(properties.provisioningState) "
            f"| take {self._config.max_resources + 1}"
        )

    def _health_query(self) -> str:
        if self._config.scope is AzureSubscriptionHealthScope.SUBSCRIPTION:
            where = ""
        else:
            filters = " or ".join(
                f"tostring(properties.targetResourceId) has '/resourceGroups/{_escaped(group)}/'"
                for group in self._config.resource_groups
            )
            where = f"| where {filters} "
        return (
            f"HealthResources {where}"
            "| project targetResourceId=tostring(properties.targetResourceId), "
            "resourceName=tostring(properties.targetResourceName), "
            "availabilityState=tostring(properties.availabilityState), "
            "reasonType=tostring(properties.reasonType), "
            "occurredTime=tostring(properties.occurredTime) | take 65"
        )


async def _emit(
    observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None,
    *,
    kind: str,
    status: str,
    label: str,
    completed: int | None = None,
    total: int | None = None,
) -> None:
    if observer is None:
        return
    await observer(
        {
            "kind": kind,
            "status": status,
            "label": label,
            "completed": completed,
            "total": total,
        }
    )


def _valid_resource(value: Mapping[str, Any]) -> bool:
    return all(
        isinstance(value.get(key), str) and value.get(key)
        for key in ("id", "name", "type", "resourceGroup")
    )


def _health_findings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("availabilityState") or "Unknown")
        if state.casefold() == "available":
            continue
        resource_id = row.get("targetResourceId")
        identity = _resource_identity(resource_id if isinstance(resource_id, str) else "")
        resource_name = row.get("resourceName")
        findings.append(
            {
                "kind": "resource_health",
                "resource_name": str(resource_name or identity["name"] or "unknown"),
                "resource_type": identity["type"],
                "resource_group": identity["resource_group"],
                "status": state,
                "reason": str(row.get("reasonType") or "unknown"),
                "title": _bounded_text(row.get("title")),
                "observed_at": str(row.get("occurredTime") or "unknown"),
            }
        )
    return findings


def _resource_identity(resource_id: str) -> dict[str, str]:
    parts = [part for part in resource_id.strip("/").split("/") if part]
    folded = [part.casefold() for part in parts]
    group = ""
    if "resourcegroups" in folded:
        group_at = folded.index("resourcegroups")
        if group_at + 1 < len(parts):
            group = parts[group_at + 1]
    if "providers" not in folded:
        return {"name": "", "type": "", "resource_group": group}
    provider_at = folded.index("providers")
    provider_parts = parts[provider_at + 1 :]
    if len(provider_parts) < 3:
        return {"name": "", "type": "", "resource_group": group}
    namespace = provider_parts[0]
    type_parts = provider_parts[1::2]
    name_parts = provider_parts[2::2]
    return {
        "name": name_parts[-1] if name_parts else "",
        "type": "/".join((namespace, *type_parts)),
        "resource_group": group,
    }


def _provisioning_findings(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bad = {"failed", "canceled", "deleting"}
    return [
        {
            "kind": "provisioning",
            "resource_name": str(row["name"]),
            "resource_type": str(row["type"]),
            "resource_group": str(row["resourceGroup"]),
            "status": str(row.get("provisioningState") or "unknown"),
        }
        for row in rows
        if str(row.get("provisioningState") or "").casefold() in bad
    ]


def _metric_value(payload: Any, aggregation: str) -> float:
    values = payload.get("value") if isinstance(payload, Mapping) else None
    if not isinstance(values, list) or not values:
        raise RuntimeError("Azure Monitor metric response is invalid")
    points: list[float] = []
    for series in values[0].get("timeseries", []) if isinstance(values[0], Mapping) else []:
        if not isinstance(series, Mapping):
            continue
        for datum in series.get("data", []):
            if isinstance(datum, Mapping) and isinstance(datum.get(aggregation), int | float):
                points.append(float(datum[aggregation]))
    if not points:
        raise RuntimeError("Azure Monitor metric has no observed points")
    return min(points) if aggregation == "minimum" else max(points)


def _escaped(value: str) -> str:
    return value.replace("'", "''")


def _bounded_text(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    return " ".join(value.split())[:128] or "unknown"


__all__ = [
    "AzureSubscriptionHealthConfig",
    "AzureSubscriptionHealthProvider",
    "AzureSubscriptionHealthScope",
    "DEFAULT_METRIC_PROBES",
    "MetricProbeSpec",
]
