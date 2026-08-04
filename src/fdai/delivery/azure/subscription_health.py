"""Bounded Azure subscription-scope health and metric sweep."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any, Final
from urllib.parse import quote

import httpx

from fdai.delivery.azure.arg_transport import ArgThrottleGate, fetch_arg_row_pages
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MANAGEMENT_AUDIENCE: Final = "https://management.azure.com/.default"
_ARG_API_VERSION: Final = "2022-10-01"
_METRICS_API_VERSION: Final = "2024-02-01"
_RESOURCE_HEALTH_API_VERSION: Final = "2025-05-01"
_SUBSCRIPTIONS_API_VERSION: Final = "2022-12-01"
_RESOURCE_HEALTH_ID_MARKER: Final = "/providers/microsoft.resourcehealth/availabilitystatuses/"
_PROVIDER_RESOURCE_TYPE: Final = re.compile(r"[A-Za-z0-9.-]+(?:/[A-Za-z0-9.-]+)+")
_PROVIDER_KIND_TOKEN: Final = re.compile(r"[a-z0-9.-]{1,64}")
_AVAILABILITY_STATE: Final = re.compile(r"[A-Za-z][A-Za-z0-9 -]{0,63}")


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
        "microsoft.cache/redis",
        "usedmemorypercentage",
        "Maximum",
        "gt",
        90.0,
    ),
    MetricProbeSpec(
        "microsoft.cache/redisenterprise",
        "usedmemorypercentage",
        "Maximum",
        "gt",
        90.0,
    ),
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
        self._arg_throttle_gate = ArgThrottleGate()
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
        return await self.query_health(
            lookback_seconds,
            include_metrics=True,
            progress_observer=progress_observer,
        )

    async def query_health(
        self,
        lookback_seconds: int,
        *,
        include_metrics: bool,
        include_service_health: bool = False,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Inspect broad health with a server-selected metric policy."""

        return await self._query(
            lookback_seconds,
            resource_types=(),
            kind_tokens_by_resource_type={},
            availability_states=(),
            include_metrics=include_metrics,
            include_service_health=include_service_health,
            include_history=False,
            progress_observer=progress_observer,
        )

    async def query_health_history(
        self,
        lookback_seconds: int,
        *,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Return bounded Resource Health events in chronological order."""

        return await self._query(
            lookback_seconds,
            resource_types=(),
            kind_tokens_by_resource_type={},
            availability_states=(),
            include_metrics=False,
            include_service_health=False,
            include_history=True,
            progress_observer=progress_observer,
        )

    async def query_resource_types(
        self,
        lookback_seconds: int,
        *,
        resource_types: tuple[str, ...],
        kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]] | None = None,
        availability_states: tuple[str, ...] = (),
        include_metrics: bool = True,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Inspect only server-selected Azure provider resource types."""

        return await self._query(
            lookback_seconds,
            resource_types=_validated_resource_types(resource_types),
            kind_tokens_by_resource_type=_validated_kind_token_map(
                resource_types,
                kind_tokens_by_resource_type or {},
            ),
            availability_states=_validated_availability_states(availability_states),
            include_metrics=include_metrics,
            include_service_health=False,
            include_history=False,
            progress_observer=progress_observer,
        )

    async def query_metric_comparison(
        self,
        *,
        anchor_at: str,
        metric_family: str,
        window_seconds: int,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Compare the same bounded metric targets before and after an incident anchor."""

        if metric_family not in {"cpu", "memory"}:
            raise ValueError("metric comparison family MUST be cpu or memory")
        if not 300 <= window_seconds <= 86_400:
            raise ValueError("metric comparison window MUST be in [300, 86400]")
        try:
            anchor = datetime.fromisoformat(anchor_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("metric comparison anchor MUST be RFC3339") from exc
        if anchor.tzinfo is None:
            raise ValueError("metric comparison anchor MUST be timezone-aware")
        anchor = anchor.astimezone(UTC)
        token = await self._identity.get_token(_MANAGEMENT_AUDIENCE)
        headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}
        resources = await self._arg(headers, self._resource_query((), {}))
        safe_resources = [item for item in resources if _valid_resource(item)][
            : self._config.max_resources
        ]
        supported = [
            item
            for item in safe_resources
            if (probe := self._probe_by_type.get(str(item["type"]).casefold())) is not None
            and metric_family in probe.metric_name.casefold()
        ]
        truncated = len(supported) > self._config.max_metric_resources
        targets = supported[: self._config.max_metric_resources]
        semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)
        before_start = anchor - timedelta(seconds=window_seconds)
        after_end = anchor + timedelta(seconds=window_seconds)

        async def compare(resource: Mapping[str, Any]) -> dict[str, Any]:
            async with semaphore:
                probe = self._probe_by_type[str(resource["type"]).casefold()]
                before, after = await asyncio.gather(
                    self._metric_between(headers, resource, probe, before_start, anchor),
                    self._metric_between(headers, resource, probe, anchor, after_end),
                )
                return {
                    "resource_name": resource["name"],
                    "resource_type": resource["type"],
                    "resource_group": resource["resourceGroup"],
                    "metric": probe.metric_name,
                    "before_value": before["value"],
                    "after_value": after["value"],
                    "delta": float(after["value"]) - float(before["value"]),
                    "before_points": len(before["points"]),
                    "after_points": len(after["points"]),
                }

        await _emit(
            progress_observer,
            kind="metrics.querying",
            status="running",
            label="Comparing incident metric windows",
            completed=0,
            total=len(targets) * 2,
        )
        comparisons: list[dict[str, Any]] = []
        unavailable = 0
        for task in asyncio.as_completed([asyncio.create_task(compare(item)) for item in targets]):
            try:
                comparisons.append(await task)
            except Exception:  # noqa: BLE001 - one target degrades comparison coverage
                unavailable += 1
        return {
            "status": "partial" if unavailable or truncated else "matched",
            "source": "azure-monitor-metrics-comparison",
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "anchor_at": _utc_z(anchor),
            "window_seconds": window_seconds,
            "metric_family": metric_family,
            "metric_checked": len(comparisons),
            "metric_unavailable": unavailable,
            "unsupported_metric_resources": len(safe_resources) - len(supported),
            "metric_comparisons": comparisons,
            "truncated": truncated,
        }

    async def _query(
        self,
        lookback_seconds: int,
        *,
        resource_types: tuple[str, ...],
        kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]],
        availability_states: tuple[str, ...],
        include_metrics: bool,
        include_service_health: bool,
        include_history: bool,
        progress_observer: Callable[[Mapping[str, Any]], Awaitable[None]] | None,
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
        if include_service_health:
            await _emit(
                progress_observer,
                kind="service-health.querying",
                status="running",
                label="Checking Service Health",
            )
        resources, health, service_health_result = await asyncio.gather(
            self._arg(
                headers,
                self._resource_query(resource_types, kind_tokens_by_resource_type),
            ),
            self._arg(
                headers,
                self._health_query(
                    resource_types,
                    availability_states,
                    lookback_seconds=lookback_seconds,
                    include_history=include_history,
                ),
            ),
            self._service_health(headers) if include_service_health else _empty_service_health(),
        )
        service_events, service_impacts, service_health_unavailable = service_health_result
        safe_resources = [item for item in resources if _valid_resource(item)]
        resource_truncated = len(safe_resources) > self._config.max_resources
        safe_resources = safe_resources[: self._config.max_resources]
        if resource_types:
            selected_ids = {str(item["id"]).casefold() for item in safe_resources}
            health = [
                item
                for item in health
                if str(item.get("targetResourceId") or "").casefold() in selected_ids
            ]
        resource_health_unavailable = 0
        direct_health_truncated = False
        if not health and not availability_states and not include_history:
            (
                health,
                resource_health_unavailable,
                direct_health_truncated,
            ) = await self._current_resource_health(headers, resource_types)
        annotation_unavailable = 0
        annotation_truncated = False
        history_annotations: list[Mapping[str, Any]] = []
        if include_history:
            try:
                history_annotations = await self._arg(
                    headers,
                    self._history_annotation_query(lookback_seconds),
                )
            except Exception:  # noqa: BLE001 - history coverage degrades independently
                annotation_unavailable = 1
            else:
                annotation_truncated = len(history_annotations) > 64
                history_annotations = history_annotations[:64]
        elif health and not include_metrics and not resource_types:
            try:
                annotations = await self._arg(headers, self._annotation_query(health))
            except Exception:  # noqa: BLE001 - cause coverage degrades independently
                annotations = []
                annotation_unavailable = 1
            else:
                annotation_truncated = len(annotations) > 64
                health = _merge_health_annotations(health, annotations[:64])
        health_findings = _health_findings(health)
        health_history_events = (
            _health_history_events(health, history_annotations) if include_history else []
        )
        service_health_events, service_health_truncated = _service_health_events(
            service_events,
            service_impacts,
            subscription_scope=self._config.scope is AzureSubscriptionHealthScope.SUBSCRIPTION,
            max_impacts=self._config.max_resources,
        )
        provisioning_findings = _provisioning_findings(safe_resources)
        state_findings = _resource_state_findings(safe_resources, availability_states)
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
        if include_service_health:
            await _emit(
                progress_observer,
                kind="service-health.completed",
                status="unavailable" if service_health_unavailable else "completed",
                label="Service Health checked",
                completed=len(service_health_events),
                total=len(service_health_events),
            )
        supported = (
            [
                item
                for item in safe_resources
                if str(item.get("type", "")).casefold() in self._probe_by_type
            ]
            if include_metrics
            else []
        )
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
        metric_observations: list[dict[str, Any]] = []
        metric_unavailable = 0
        metric_completed = 0
        try:
            for task in asyncio.as_completed(metric_tasks):
                try:
                    result = await task
                except Exception:  # noqa: BLE001 - one failure produces partial evidence
                    metric_unavailable += 1
                else:
                    metric_observations.append(result)
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
        findings = [
            *health_findings,
            *provisioning_findings,
            *state_findings,
            *metric_findings,
        ]
        unsupported_metric_resources = (
            len(safe_resources) - len(supported) if include_metrics else 0
        )
        truncated = (
            resource_truncated
            or health_truncated
            or metric_truncated
            or annotation_truncated
            or service_health_truncated
        )
        active_service_issues = [
            event
            for event in service_health_events
            if str(event.get("event_type") or "").casefold() == "serviceissue"
        ]
        active_maintenance = [
            event
            for event in service_health_events
            if str(event.get("event_type") or "").casefold() == "plannedmaintenance"
        ]
        active_advisories = [
            event
            for event in service_health_events
            if str(event.get("event_type") or "").casefold() == "healthadvisory"
        ]
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
                    or annotation_unavailable
                    or service_health_unavailable
                    or metric_unavailable
                    or unsupported_metric_resources
                    or truncated
                )
                else "matched"
            ),
            "source": (
                "azure-resource-graph+resource-health+azure-monitor-metrics"
                if include_metrics
                else (
                    "azure-resource-graph+resource-health-history"
                    if include_history
                    else (
                        "azure-resource-graph+resource-health+service-health"
                        if include_service_health
                        else "azure-resource-graph+resource-health"
                    )
                )
            ),
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "resource_count": len(safe_resources),
            "resource_health_unavailable": resource_health_unavailable,
            "resource_annotation_unavailable": annotation_unavailable,
            "service_health_requested": include_service_health,
            "service_health_unavailable": service_health_unavailable,
            "active_service_issue_count": len(active_service_issues),
            "active_service_issue_resource_count": _impacted_resource_count(active_service_issues),
            "active_planned_maintenance_count": len(active_maintenance),
            "active_planned_maintenance_resource_count": _impacted_resource_count(
                active_maintenance
            ),
            "active_health_advisory_count": len(active_advisories),
            "active_health_advisory_resource_count": _impacted_resource_count(active_advisories),
            "service_health_events": service_health_events[:64],
            "health_history_requested": include_history,
            "health_history_events": health_history_events[:64],
            "metrics_requested": include_metrics,
            "supported_metric_resources": len(supported),
            "metric_checked": len(metric_targets) - metric_unavailable,
            "metric_unavailable": metric_unavailable,
            "unsupported_metric_resources": unsupported_metric_resources,
            "metric_observations": metric_observations[:64],
            "truncated": truncated,
            "findings": findings[:64],
        }

    async def _service_health(
        self,
        headers: Mapping[str, str],
    ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], int]:
        try:
            events, impacts = await asyncio.gather(
                self._arg(headers, self._service_health_event_query()),
                self._arg(headers, self._service_health_impact_query()),
            )
        except Exception:  # noqa: BLE001 - Service Health degrades independently
            return [], [], 1
        return events, impacts, 0

    async def _current_resource_health(
        self,
        headers: Mapping[str, str],
        resource_types: tuple[str, ...],
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
                return self._resource_health_rows(response, scope_prefix, resource_types)

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
        resource_types: tuple[str, ...],
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
            if resource_types and not _resource_id_matches_types(
                target_resource_id,
                resource_types,
            ):
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
        rows = await fetch_arg_row_pages(
            identity=self._identity,
            http_client=self._http,
            audience=_MANAGEMENT_AUDIENCE,
            endpoint=self._config.endpoint,
            api_version=_ARG_API_VERSION,
            subscriptions=(self._config.subscription_id,),
            query=query,
            result_name="subscription health",
            page_size=1000,
            max_pages=1,
            max_records=1000,
            timeout_seconds=self._config.timeout_seconds,
            error_type=RuntimeError,
            throttle_gate=self._arg_throttle_gate,
            request_headers=headers,
            allow_truncated_without_token=True,
            max_response_bytes=self._config.max_response_bytes,
        )
        return list(rows)

    async def _metric(
        self,
        headers: Mapping[str, str],
        resource: Mapping[str, Any],
        probe: MetricProbeSpec,
        lookback_seconds: int,
    ) -> dict[str, Any]:
        until = datetime.now(tz=UTC)
        since = until - timedelta(seconds=lookback_seconds)
        return await self._metric_between(headers, resource, probe, since, until)

    async def _metric_between(
        self,
        headers: Mapping[str, str],
        resource: Mapping[str, Any],
        probe: MetricProbeSpec,
        since: datetime,
        until: datetime,
    ) -> dict[str, Any]:
        resource_id = str(resource["id"])
        response = await self._http.get(
            f"{self._config.endpoint.rstrip('/')}{quote(resource_id, safe='/')}"
            "/providers/Microsoft.Insights/metrics",
            params={
                "api-version": _METRICS_API_VERSION,
                "metricnames": probe.metric_name,
                "aggregation": probe.aggregation,
                "interval": "PT5M",
                "timespan": f"{_utc_z(since)}/{_utc_z(until)}",
            },
            headers=dict(headers),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code >= 400 or len(response.content) > self._config.max_response_bytes:
            raise RuntimeError("Azure Monitor metric query unavailable")
        points = _metric_points(response.json(), probe.aggregation.casefold())
        values = [float(point["value"]) for point in points]
        value = min(values) if probe.aggregation.casefold() == "minimum" else max(values)
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
            "points": points,
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

    def _resource_query(
        self,
        resource_types: tuple[str, ...],
        kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]],
    ) -> str:
        scope_filter = self._scope_filter("resourceGroup")
        filters = [scope_filter] if scope_filter is not None else []
        if resource_types:
            kind_lookup = {
                resource_type.casefold(): tokens
                for resource_type, tokens in kind_tokens_by_resource_type.items()
            }
            clauses: list[str] = []
            for resource_type in resource_types:
                clause = f"type =~ '{_escaped(resource_type)}'"
                tokens = kind_lookup.get(resource_type.casefold(), ())
                if tokens:
                    token_clause = " or ".join(f"kind has '{_escaped(token)}'" for token in tokens)
                    clause = f"({clause} and ({token_clause}))"
                clauses.append(clause)
            filters.append(f"({' or '.join(clauses)})")
        where = "".join(f"| where {item} " for item in filters)
        return (
            f"Resources {where}"
            "| project id, name, type, resourceGroup, location, "
            "provisioningState=tostring(properties.provisioningState), "
            "state=tostring(properties.state), status=tostring(properties.status), "
            "resourceState=tostring(properties.resourceState) "
            f"| take {self._config.max_resources + 1}"
        )

    def _health_query(
        self,
        resource_types: tuple[str, ...],
        availability_states: tuple[str, ...],
        *,
        lookback_seconds: int,
        include_history: bool,
    ) -> str:
        filters = ["type =~ 'microsoft.resourcehealth/availabilitystatuses'"]
        if self._config.scope is AzureSubscriptionHealthScope.SUBSCRIPTION:
            pass
        else:
            group_filters = " or ".join(
                f"tostring(properties.targetResourceId) has '/resourceGroups/{_escaped(group)}/'"
                for group in self._config.resource_groups
            )
            filters.append(f"({group_filters})")
        if resource_types:
            values = ", ".join(f"'{_escaped(item)}'" for item in resource_types)
            filters.append(f"tostring(properties.targetResourceType) in~ ({values})")
        if availability_states:
            values = ", ".join(f"'{_escaped(item)}'" for item in availability_states)
            filters.append(f"tostring(properties.availabilityState) in~ ({values})")
        if include_history:
            filters.append(f"todatetime(properties.occurredTime) >= ago({lookback_seconds}s)")
        where = "".join(f"| where {item} " for item in filters)
        query = (
            f"HealthResources {where}"
            "| project targetResourceId=tostring(properties.targetResourceId), "
            "targetResourceType=tostring(properties.targetResourceType), "
            "resourceName=tostring(properties.targetResourceName), "
            "availabilityState=tostring(properties.availabilityState), "
            "reasonType=tostring(properties.reasonType), "
            "occurredTime=tostring(properties.occurredTime) "
        )
        if include_history:
            query += "| order by occurredTime asc "
        return query + "| take 65"

    def _annotation_query(self, health: Sequence[Mapping[str, Any]]) -> str:
        target_ids = tuple(
            dict.fromkeys(
                str(item.get("targetResourceId"))
                for item in health
                if isinstance(item.get("targetResourceId"), str)
                and str(item["targetResourceId"])
                .casefold()
                .startswith(f"/subscriptions/{self._config.subscription_id.casefold()}/")
            )
        )
        values = ", ".join(f"'{_escaped(item)}'" for item in target_ids[:64])
        return (
            "HealthResources "
            "| where type =~ 'microsoft.resourcehealth/resourceannotations' "
            f"| where tostring(properties.targetResourceId) in~ ({values}) "
            "| project targetResourceId=tostring(properties.targetResourceId), "
            "annotationName=tostring(properties.annotationName), "
            "context=tostring(properties.context), reason=tostring(properties.reason), "
            "occurredTime=tostring(properties.occurredTime) "
            "| order by occurredTime desc | take 65"
        )

    def _history_annotation_query(self, lookback_seconds: int) -> str:
        filters = ["type =~ 'microsoft.resourcehealth/resourceannotations'"]
        if self._config.scope is not AzureSubscriptionHealthScope.SUBSCRIPTION:
            group_filters = " or ".join(
                f"tostring(properties.targetResourceId) has '/resourceGroups/{_escaped(group)}/'"
                for group in self._config.resource_groups
            )
            filters.append(f"({group_filters})")
        filters.append(f"todatetime(properties.occurredTime) >= ago({lookback_seconds}s)")
        where = "".join(f"| where {item} " for item in filters)
        return (
            f"HealthResources {where}"
            "| project targetResourceId=tostring(properties.targetResourceId), "
            "annotationName=tostring(properties.annotationName), "
            "context=tostring(properties.context), reason=tostring(properties.reason), "
            "occurredTime=tostring(properties.occurredTime) "
            "| order by occurredTime asc | take 65"
        )

    def _service_health_event_query(self) -> str:
        return (
            "ServiceHealthResources "
            "| where type =~ 'microsoft.resourcehealth/events' "
            "| where tostring(properties.Status) =~ 'Active' "
            "| project eventName=name, trackingId=tostring(properties.TrackingId), "
            "eventType=tostring(properties.EventType), status=tostring(properties.Status), "
            "level=tostring(properties.Level), title=tostring(properties.Title), "
            "impactStartTime=tostring(properties.ImpactStartTime) "
            "| take 65"
        )

    def _service_health_impact_query(self) -> str:
        scope_filter = self._scope_filter("tostring(properties.resourceGroup)")
        where = f"| where {scope_filter} " if scope_filter is not None else ""
        return (
            "ServiceHealthResources "
            "| where type =~ 'microsoft.resourcehealth/events/impactedresources' "
            f"{where}"
            "| extend parentEventId=tostring(split(id, '/impactedResources/')[0]) "
            "| project eventTrackingId=tostring(split(parentEventId, '/events/')[1]), "
            "targetResourceId=tostring(properties.targetResourceId), "
            "resourceName=tostring(properties.resourceName), "
            "resourceGroup=tostring(properties.resourceGroup), "
            "targetResourceType=tostring(properties.targetResourceType), "
            "targetRegion=tostring(properties.targetRegion), "
            "status=tostring(properties.status) "
            f"| take {self._config.max_resources + 1}"
        )


def _validated_resource_types(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values))
    if not normalized or len(normalized) > 64:
        raise ValueError("resource type filter requires between 1 and 64 values")
    if any(
        len(item) > 256 or _PROVIDER_RESOURCE_TYPE.fullmatch(item) is None for item in normalized
    ):
        raise ValueError("resource type filter contains an invalid provider type")
    return normalized


def _validated_kind_tokens(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values))
    if len(normalized) > 16 or any(
        _PROVIDER_KIND_TOKEN.fullmatch(item) is None for item in normalized
    ):
        raise ValueError("kind token filter contains an invalid value")
    return normalized


def _validated_kind_token_map(
    resource_types: Sequence[str],
    values: Mapping[str, Sequence[str]],
) -> Mapping[str, tuple[str, ...]]:
    known_types = {item.casefold() for item in resource_types}
    if any(resource_type.casefold() not in known_types for resource_type in values):
        raise ValueError("kind token filter contains an unknown resource type")
    return {
        resource_type: _validated_kind_tokens(tokens) for resource_type, tokens in values.items()
    }


def _validated_availability_states(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values))
    if len(normalized) > 16 or any(
        _AVAILABILITY_STATE.fullmatch(item) is None for item in normalized
    ):
        raise ValueError("availability state filter contains an invalid value")
    return normalized


def _resource_id_matches_types(resource_id: str, resource_types: Sequence[str]) -> bool:
    observed_type = _resource_identity(resource_id)["type"].casefold()
    return observed_type in {item.casefold() for item in resource_types}


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


async def _empty_service_health() -> tuple[
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
    int,
]:
    return [], [], 0


def _service_health_events(
    events: Sequence[Mapping[str, Any]],
    impacts: Sequence[Mapping[str, Any]],
    *,
    subscription_scope: bool,
    max_impacts: int,
) -> tuple[list[dict[str, Any]], bool]:
    impacts_by_event: dict[str, list[Mapping[str, Any]]] = {}
    for impact in impacts[: max_impacts + 1]:
        tracking_id = str(impact.get("eventTrackingId") or "").strip().casefold()
        if tracking_id:
            impacts_by_event.setdefault(tracking_id, []).append(impact)
    normalized: list[dict[str, Any]] = []
    for event in events[:65]:
        tracking_id = str(event.get("trackingId") or "").strip()
        event_name = str(event.get("eventName") or "").strip()
        aliases = {value.casefold() for value in (tracking_id, event_name) if value}
        matched_impacts = [
            impact for alias in aliases for impact in impacts_by_event.get(alias, ())
        ]
        if not subscription_scope and not matched_impacts:
            continue
        impacted_resources: list[dict[str, str]] = []
        seen_resources: set[tuple[str, str, str]] = set()
        for impact in matched_impacts:
            name = _bounded_text(impact.get("resourceName"))
            resource_group = _bounded_text(impact.get("resourceGroup"))
            resource_type = _bounded_text(impact.get("targetResourceType"))
            resource_key = (name.casefold(), resource_group.casefold(), resource_type.casefold())
            if resource_key in seen_resources:
                continue
            seen_resources.add(resource_key)
            impacted_resources.append(
                {
                    "name": name,
                    "resource_group": resource_group,
                    "resource_type": resource_type,
                    "region": _bounded_text(impact.get("targetRegion")),
                    "status": _bounded_text(impact.get("status")),
                }
            )
        normalized.append(
            {
                "event_type": _bounded_text(event.get("eventType")),
                "status": _bounded_text(event.get("status")),
                "level": _bounded_text(event.get("level")),
                "title": _bounded_text(event.get("title")),
                "impact_start_time": _bounded_text(event.get("impactStartTime")),
                "impacted_resource_count": len(impacted_resources),
                "impacted_resources": impacted_resources[:64],
            }
        )
    return normalized[:64], len(events) > 64 or len(impacts) > max_impacts


def _impacted_resource_count(events: Sequence[Mapping[str, Any]]) -> int:
    resources: set[tuple[str, str, str]] = set()
    for event in events:
        impacted = event.get("impacted_resources")
        if not isinstance(impacted, list):
            continue
        for resource in impacted:
            if not isinstance(resource, Mapping):
                continue
            resources.add(
                (
                    str(resource.get("name") or "").casefold(),
                    str(resource.get("resource_group") or "").casefold(),
                    str(resource.get("resource_type") or "").casefold(),
                )
            )
    return len(resources)


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


def _health_history_events(
    health: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in health:
        resource_id = row.get("targetResourceId")
        identity = _resource_identity(resource_id if isinstance(resource_id, str) else "")
        events.append(
            {
                "kind": "availability_status",
                "resource_name": str(row.get("resourceName") or identity["name"] or "unknown"),
                "resource_type": identity["type"],
                "resource_group": identity["resource_group"],
                "status": str(row.get("availabilityState") or "Unknown"),
                "reason": str(row.get("reasonType") or "unknown"),
                "classification": _health_event_classification(row.get("reasonType")),
                "title": _bounded_text(row.get("title")),
                "observed_at": str(row.get("occurredTime") or "unknown"),
            }
        )
    for row in annotations:
        resource_id = row.get("targetResourceId")
        identity = _resource_identity(resource_id if isinstance(resource_id, str) else "")
        events.append(
            {
                "kind": "resource_annotation",
                "resource_name": identity["name"] or "unknown",
                "resource_type": identity["type"],
                "resource_group": identity["resource_group"],
                "status": _bounded_text(row.get("annotationName")),
                "reason": _bounded_text(row.get("context") or row.get("reason")),
                "classification": _health_event_classification(row.get("context")),
                "title": _bounded_text(row.get("reason")),
                "observed_at": str(row.get("occurredTime") or "unknown"),
            }
        )
    return sorted(events, key=lambda event: event["observed_at"])[:64]


def _health_event_classification(value: object) -> str:
    normalized = str(value or "").casefold()
    if "customer" in normalized:
        return "customer-initiated"
    if "platform" in normalized:
        return "platform-initiated"
    return "status-only"


def _merge_health_annotations(
    health: Sequence[Mapping[str, Any]],
    annotations: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    reason_by_target: dict[str, str] = {}
    for annotation in annotations:
        target = annotation.get("targetResourceId")
        if not isinstance(target, str) or target.casefold() in reason_by_target:
            continue
        candidates = tuple(
            str(annotation.get(field) or "").strip()
            for field in ("context", "reason", "annotationName")
        )
        recognized = next(
            (
                "Customer Initiated" if "customer" in candidate.casefold() else "Platform Initiated"
                for candidate in candidates
                if "customer" in candidate.casefold() or "platform" in candidate.casefold()
            ),
            None,
        )
        fallback = next((candidate for candidate in candidates if candidate), None)
        if recognized or fallback:
            reason_by_target[target.casefold()] = recognized or fallback or "unknown"
    merged: list[Mapping[str, Any]] = []
    for row in health:
        reason = str(row.get("reasonType") or "").strip()
        target = str(row.get("targetResourceId") or "").casefold()
        if not reason or reason.casefold() == "unknown":
            reason = reason_by_target.get(target, reason or "unknown")
        merged.append({**row, "reasonType": reason})
    return merged


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


def _resource_state_findings(
    rows: Sequence[Mapping[str, Any]],
    requested_states: Sequence[str],
) -> list[dict[str, Any]]:
    requested = {state.casefold() for state in requested_states}
    findings: list[dict[str, Any]] = []
    for row in rows:
        observed = next(
            (
                str(row[field])
                for field in ("state", "status", "resourceState")
                if isinstance(row.get(field), str) and str(row[field]).strip()
            ),
            "",
        )
        if observed.casefold() not in requested:
            continue
        findings.append(
            {
                "kind": "resource_state",
                "resource_name": str(row["name"]),
                "resource_type": str(row["type"]),
                "resource_group": str(row["resourceGroup"]),
                "status": observed,
            }
        )
    return findings


def _metric_points(payload: Any, aggregation: str) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, Mapping) else None
    if not isinstance(values, list) or not values:
        raise RuntimeError("Azure Monitor metric response is invalid")
    points: list[dict[str, Any]] = []
    for series in values[0].get("timeseries", []) if isinstance(values[0], Mapping) else []:
        if not isinstance(series, Mapping):
            continue
        for datum in series.get("data", []):
            if isinstance(datum, Mapping) and isinstance(datum.get(aggregation), int | float):
                timestamp = datum.get("timeStamp") or datum.get("timestamp")
                points.append(
                    {
                        "timestamp": timestamp if isinstance(timestamp, str) else "",
                        "value": float(datum[aggregation]),
                    }
                )
    if not points:
        raise RuntimeError("Azure Monitor metric has no observed points")
    return points


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
