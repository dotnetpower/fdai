"""Read-only observation-depth console tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_int,
    _optional_str,
    _require_str,
)
from fdai.shared.providers.observation import (
    DeploymentHistoryProvider,
    IncidentCorrelator,
    LogQueryProvider,
    MetricQueryProvider,
    ObservationError,
)


class QueryLogTool:
    """Run a bounded log query and return the raw rows."""

    name = "query_log"
    description = (
        "Run a bounded log query and return the rows. Read-only; abstains when the provider raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, provider: LogQueryProvider) -> None:
        self._provider = provider

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        query = _require_str(arguments, "query").strip()
        window = _require_str(arguments, "window").strip()
        if not query:
            return ToolResult(status="error", preview="query_log requires a non-empty 'query'")
        if not window:
            return ToolResult(status="error", preview="query_log requires a non-empty 'window'")
        max_rows = _optional_int(arguments, "max_rows", default=100, minimum=1, maximum=500)
        try:
            result = asyncio.run(
                self._provider.query_log(query=query, window=window, max_rows=max_rows)
            )
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"query_log abstains: {exc}",
                data={"query": query, "window": window},
            )
        except RuntimeError as exc:
            return ToolResult(status="error", preview=f"query_log event-loop reuse: {exc}")
        rows = [dict(row) for row in result.rows]
        preview = f"query_log[{window}]: {len(rows)} row(s)" + (
            " (truncated)" if result.truncated else ""
        )
        return ToolResult(
            status="ok" if rows else "abstain",
            data={
                "query": query,
                "window": window,
                "rows": rows,
                "truncated": result.truncated,
                "scanned_records": result.scanned_records,
            },
            preview=preview,
        )


class QueryMetricTool:
    """Return a metric aggregation over a bounded window."""

    name = "query_metric"
    description = (
        "Return a metric aggregation timeseries. Read-only; abstains when the provider raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, provider: MetricQueryProvider) -> None:
        self._provider = provider

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        namespace = _require_str(arguments, "namespace").strip()
        metric = _require_str(arguments, "metric").strip()
        aggregation = _require_str(arguments, "aggregation").strip()
        window = _require_str(arguments, "window").strip()
        for name, value in (
            ("namespace", namespace),
            ("metric", metric),
            ("aggregation", aggregation),
            ("window", window),
        ):
            if not value:
                return ToolResult(
                    status="error",
                    preview=f"query_metric requires a non-empty {name!r}",
                )
        try:
            result = asyncio.run(
                self._provider.query_metric(
                    namespace=namespace,
                    metric=metric,
                    aggregation=aggregation,
                    window=window,
                )
            )
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"query_metric abstains: {exc}",
                data={
                    "namespace": namespace,
                    "metric": metric,
                    "aggregation": aggregation,
                    "window": window,
                },
            )
        except RuntimeError as exc:
            return ToolResult(status="error", preview=f"query_metric event-loop reuse: {exc}")
        points = [{"timestamp": point.timestamp, "value": point.value} for point in result.points]
        return ToolResult(
            status="ok" if points else "abstain",
            data={
                "namespace": namespace,
                "metric": metric,
                "aggregation": aggregation,
                "window": window,
                "points": points,
            },
            preview=f"query_metric[{namespace}/{metric}]: {len(points)} point(s)",
        )


class QueryDeploymentsTool:
    """Return deployment history for a window and optional resource."""

    name = "query_deployments"
    description = (
        "Return deployment records over a time window, optionally filtered "
        "by resource_ref. Read-only; abstains when the provider raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, provider: DeploymentHistoryProvider) -> None:
        self._provider = provider

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        window = _require_str(arguments, "window").strip()
        if not window:
            return ToolResult(
                status="error", preview="query_deployments requires a non-empty 'window'"
            )
        resource_ref = _optional_str(arguments, "resource_ref", default="") or None
        if resource_ref is not None and not resource_ref.strip():
            resource_ref = None
        try:
            result = asyncio.run(
                self._provider.query_deployments(window=window, resource_ref=resource_ref)
            )
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"query_deployments abstains: {exc}",
                data={"window": window, "resource_ref": resource_ref},
            )
        except RuntimeError as exc:
            return ToolResult(status="error", preview=f"query_deployments event-loop reuse: {exc}")
        records = [_project_deployment_record(record) for record in result.records]
        return ToolResult(
            status="ok" if records else "abstain",
            data={"window": window, "resource_ref": resource_ref, "records": records},
            preview=f"query_deployments[{window}]: {len(records)} deployment(s)",
            evidence_refs=tuple(f"deployment:{record['deployment_ref']}" for record in records),
        )


class CorrelateIncidentTool:
    """Return the multi-signal correlation for one incident id."""

    name = "correlate_incident"
    description = (
        "Return the multi-signal correlation (events, audit, logs, metrics, "
        "deployments) for one incident_id. Read-only; abstains when the "
        "correlator raises."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, correlator: IncidentCorrelator) -> None:
        self._correlator = correlator

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        incident_id = _require_str(arguments, "incident_id").strip()
        if not incident_id:
            return ToolResult(
                status="error",
                preview="correlate_incident requires a non-empty 'incident_id'",
            )
        try:
            correlation = asyncio.run(self._correlator.correlate(incident_id=incident_id))
        except ObservationError as exc:
            return ToolResult(
                status="abstain",
                preview=f"correlate_incident abstains: {exc}",
                data={"incident_id": incident_id},
            )
        except RuntimeError as exc:
            return ToolResult(
                status="error",
                preview=f"correlate_incident event-loop reuse: {exc}",
            )
        preview = (
            f"correlate_incident[{incident_id}]: "
            f"{len(correlation.events)} evt / {len(correlation.audit_entries)} audit / "
            f"{len(correlation.log_hits)} log / {len(correlation.metric_points)} metric / "
            f"{len(correlation.deployments)} deploy"
        )
        return ToolResult(
            status="ok",
            data={
                "incident_id": correlation.incident_id,
                "events": [dict(event) for event in correlation.events],
                "audit_entries": [dict(entry) for entry in correlation.audit_entries],
                "log_hits": [dict(hit) for hit in correlation.log_hits],
                "metric_points": [
                    {"timestamp": point.timestamp, "value": point.value}
                    for point in correlation.metric_points
                ],
                "deployments": [
                    _project_deployment_record(record) for record in correlation.deployments
                ],
            },
            preview=preview,
            evidence_refs=(f"incident:{correlation.incident_id}",),
        )


def _project_deployment_record(record: Any) -> dict[str, Any]:
    return {
        "deployment_ref": record.deployment_ref,
        "timestamp": record.timestamp,
        "author": record.author,
        "resource_refs": list(record.resource_refs),
        "status": record.status,
    }
