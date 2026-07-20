"""Typed Azure Monitor Logs adapters for RCA log and trace evidence."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from fdai.delivery.azure.log_query import AzureLogAnalyticsQueryProvider
from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProviderError,
    LogRecord,
)
from fdai.shared.providers.trace_query import (
    Span,
    TraceQuery,
    TraceQueryProviderError,
)

_DEFAULT_LIMIT: Final[int] = 100
_MAX_LIMIT: Final[int] = 500
_MAX_WINDOW: Final[timedelta] = timedelta(days=31)
_RESOURCE_LABEL: Final[str] = "resource_id"
_SEVERITIES: Final[tuple[str, ...]] = (
    "verbose",
    "information",
    "warning",
    "error",
    "critical",
)


class AzureLogAnalyticsRcaLogProvider:
    """Project workspace-based Application Insights logs into ``LogRecord``."""

    def __init__(self, query_provider: AzureLogAnalyticsQueryProvider) -> None:
        self._query_provider = query_provider

    async def query(self, query: LogQuery) -> AsyncIterator[LogRecord]:
        try:
            since, until, limit = _bounds(query.since, query.until, query.limit)
            resource_ref = _resource_ref(query.labels)
            kql = _log_kql(
                since=since,
                until=until,
                resource_ref=resource_ref,
                body_filter=query.expression,
            )
            result = await self._query_provider.query_log(
                query=kql,
                window=_duration(until - since),
                max_rows=limit,
            )
            records = tuple(_log_record(row) for row in result.rows)
        except Exception as exc:  # noqa: BLE001 - normalize delivery failures at provider seam
            if isinstance(exc, LogQueryProviderError):
                raise
            raise LogQueryProviderError("Azure Monitor RCA log query failed") from exc
        for record in records:
            yield record


class AzureLogAnalyticsTraceProvider:
    """Project AppRequests and AppDependencies rows into distributed spans."""

    def __init__(self, query_provider: AzureLogAnalyticsQueryProvider) -> None:
        self._query_provider = query_provider

    async def query(self, query: TraceQuery) -> AsyncIterator[Span]:
        try:
            since, until, limit = _bounds(query.since, query.until, query.limit)
            resource_ref = _resource_ref(query.labels)
            kql = _trace_kql(
                since=since,
                until=until,
                resource_ref=resource_ref,
                trace_id=query.trace_id,
                service=query.service,
                operation=query.operation,
                min_duration=query.min_duration,
            )
            result = await self._query_provider.query_log(
                query=kql,
                window=_duration(until - since),
                max_rows=limit,
            )
            spans = tuple(_span(row) for row in result.rows)
        except Exception as exc:  # noqa: BLE001 - normalize delivery failures at provider seam
            if isinstance(exc, TraceQueryProviderError):
                raise
            raise TraceQueryProviderError("Azure Monitor trace query failed") from exc
        for span in spans:
            yield span


def _bounds(
    since: datetime | None,
    until: datetime | None,
    requested_limit: int | None,
) -> tuple[datetime, datetime, int]:
    if since is None or until is None:
        raise ValueError("Azure Monitor telemetry queries require since and until")
    if since.tzinfo is None or until.tzinfo is None:
        raise ValueError("Azure Monitor telemetry bounds MUST include timezone")
    normalized_since = since.astimezone(UTC)
    normalized_until = until.astimezone(UTC)
    window = normalized_until - normalized_since
    if window <= timedelta(0) or window > _MAX_WINDOW:
        raise ValueError("Azure Monitor telemetry window MUST be in (0, 31 days]")
    limit = requested_limit if requested_limit is not None else _DEFAULT_LIMIT
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"Azure Monitor telemetry limit MUST be in [1, {_MAX_LIMIT}]")
    return normalized_since, normalized_until, limit


def _resource_ref(labels: Mapping[str, str]) -> str | None:
    unsupported = set(labels) - {_RESOURCE_LABEL}
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"unsupported Azure Monitor telemetry labels: {names}")
    value = labels.get(_RESOURCE_LABEL)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _log_kql(
    *,
    since: datetime,
    until: datetime,
    resource_ref: str | None,
    body_filter: str,
) -> str:
    filters = _common_filters(since=since, until=until, resource_ref=resource_ref)
    if body_filter.strip():
        filters.append(f"| where body contains {_kql_string(body_filter.strip())}")
    filters.extend(("| order by at asc",))
    return "\n".join(
        (
            "union isfuzzy=true",
            "(AppTraces | project at=TimeGenerated, "
            "body=tostring(column_ifexists('Message', '')), "
            "severity=tostring(column_ifexists('SeverityLevel', 0)), "
            "service=tostring(column_ifexists('AppRoleName', '')), "
            "resource_id=tostring(column_ifexists('_ResourceId', ''))),",
            "(AppExceptions | project at=TimeGenerated, "
            "body=tostring(column_ifexists('OuterMessage', '')), "
            "severity=tostring(column_ifexists('SeverityLevel', 3)), "
            "service=tostring(column_ifexists('AppRoleName', '')), "
            "resource_id=tostring(column_ifexists('_ResourceId', '')))",
            *filters,
            "| project at, body, severity, service, resource_id",
        )
    )


def _trace_kql(
    *,
    since: datetime,
    until: datetime,
    resource_ref: str | None,
    trace_id: str | None,
    service: str | None,
    operation: str | None,
    min_duration: timedelta | None,
) -> str:
    filters = _common_filters(since=since, until=until, resource_ref=resource_ref)
    for column, value in (
        ("trace_id", trace_id),
        ("service", service),
        ("operation", operation),
    ):
        if value is not None and value.strip():
            filters.append(f"| where {column} == {_kql_string(value.strip())}")
    if min_duration is not None:
        if min_duration < timedelta(0):
            raise ValueError("TraceQuery.min_duration MUST be non-negative")
        filters.append(f"| where duration_ms >= {min_duration.total_seconds() * 1000:.3f}")
    filters.extend(("| order by at asc",))
    return "\n".join(
        (
            "union isfuzzy=true",
            "(AppRequests | project at=TimeGenerated, "
            "trace_id=tostring(column_ifexists('OperationId', '')), "
            "span_id=tostring(column_ifexists('Id', '')), "
            "parent_span_id=tostring(column_ifexists('ParentId', '')), "
            "service=tostring(column_ifexists('AppRoleName', '')), "
            "operation=tostring(column_ifexists('Name', '')), "
            "duration_ms=todouble(column_ifexists('DurationMs', 0.0)), "
            "success=tobool(column_ifexists('Success', false)), "
            "resource_id=tostring(column_ifexists('_ResourceId', ''))),",
            "(AppDependencies | project at=TimeGenerated, "
            "trace_id=tostring(column_ifexists('OperationId', '')), "
            "span_id=tostring(column_ifexists('Id', '')), "
            "parent_span_id=tostring(column_ifexists('ParentId', '')), "
            "service=tostring(column_ifexists('AppRoleName', '')), "
            "operation=tostring(column_ifexists('Name', '')), "
            "duration_ms=todouble(column_ifexists('DurationMs', 0.0)), "
            "success=tobool(column_ifexists('Success', false)), "
            "resource_id=tostring(column_ifexists('_ResourceId', '')))",
            *filters,
            "| project at, trace_id, span_id, parent_span_id, service, operation, "
            "duration_ms, success, resource_id",
        )
    )


def _common_filters(*, since: datetime, until: datetime, resource_ref: str | None) -> list[str]:
    filters = [
        f"| where at between (datetime({since.isoformat()}) .. datetime({until.isoformat()}))"
    ]
    if resource_ref is not None:
        filters.append(f"| where resource_id =~ {_kql_string(resource_ref)}")
    return filters


def _log_record(row: Mapping[str, Any]) -> LogRecord:
    severity_raw = str(row.get("severity") or "information")
    try:
        severity_index = int(severity_raw)
    except ValueError:
        severity = severity_raw.casefold()
    else:
        severity = _SEVERITIES[min(max(severity_index, 0), len(_SEVERITIES) - 1)]
    return LogRecord(
        at=_timestamp(row.get("at")),
        body=str(row.get("body") or ""),
        severity=severity,
        labels=_labels(row),
    )


def _span(row: Mapping[str, Any]) -> Span:
    parent = str(row.get("parent_span_id") or "").strip() or None
    success = row.get("success")
    return Span(
        trace_id=_required_text(row, "trace_id"),
        span_id=_required_text(row, "span_id"),
        parent_span_id=parent,
        service=str(row.get("service") or "unknown"),
        operation=str(row.get("operation") or "unknown"),
        start=_timestamp(row.get("at")),
        duration=timedelta(milliseconds=_non_negative_float(row.get("duration_ms"))),
        status="ok" if success is True else "error" if success is False else "unset",
        labels=_labels(row),
    )


def _labels(row: Mapping[str, Any]) -> dict[str, str]:
    resource_ref = str(row.get("resource_id") or "").strip()
    return {_RESOURCE_LABEL: resource_ref} if resource_ref else {}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Azure Monitor telemetry row is missing a timestamp")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Azure Monitor telemetry timestamp MUST include timezone")
    return parsed.astimezone(UTC)


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"Azure Monitor telemetry row is missing {key}")
    return value


def _non_negative_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Azure Monitor telemetry duration is malformed")
    numeric = float(value)
    if numeric < 0:
        raise ValueError("Azure Monitor telemetry duration MUST be non-negative")
    return numeric


def _kql_string(value: str) -> str:
    if len(value) > 2_000:
        raise ValueError("Azure Monitor telemetry filter exceeds 2000 characters")
    return "'" + value.replace("'", "''") + "'"


def _duration(value: timedelta) -> str:
    return f"PT{value.total_seconds():.3f}S"


__all__ = [
    "AzureLogAnalyticsRcaLogProvider",
    "AzureLogAnalyticsTraceProvider",
]
