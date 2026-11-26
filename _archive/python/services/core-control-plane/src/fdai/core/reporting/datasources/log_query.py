"""Log-query datasource - wraps ``shared.providers.log_query.LogQueryProvider``.

Streams structured log records into report shapes:

- ``projection="rows"`` (default) -> list_stream / table: one row per
  record with ``at / severity / body / labels``.
- ``projection="count_by_severity"`` -> bar_chart / table.
- ``projection="count_total"`` -> query_value.

Query parameters:

- ``expression`` (str, required): vendor-specific query string (KQL,
  LogQL, ...).
- ``labels`` (mapping, optional): CSP-neutral pre-filter labels.
- ``limit`` (int, optional): row limit forwarded to the provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fdai.core.reporting.models import DataSet, QuerySpec
from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProvider,
    LogRecord,
)


class LogQueryDataSource:
    """Projection over :class:`~fdai.shared.providers.log_query.LogQueryProvider`."""

    __slots__ = ("_name", "_provider")

    def __init__(
        self,
        *,
        provider: LogQueryProvider,
        name: str = "log_query",
    ) -> None:
        self._name = name
        self._provider = provider

    @property
    def name(self) -> str:
        return self._name

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        del variables
        params = spec.parameters
        expression = str(params.get("expression") or "")
        if not expression:
            return DataSet(metadata={"error": "expression required"})
        labels_raw = params.get("labels") or {}
        limit = params.get("limit")
        limit_int: int | None
        try:
            limit_int = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit_int = None

        query = LogQuery(
            expression=expression,
            labels={str(k): str(v) for k, v in _as_mapping(labels_raw).items()},
            since=since,
            until=until,
            limit=limit_int,
        )

        records: list[LogRecord] = []
        async for record in self._provider.query(query):
            records.append(record)

        projection = str(params.get("projection", "rows"))
        if projection == "count_by_severity":
            return _count_by_severity(records)
        if projection == "count_total":
            return DataSet(scalar=len(records))
        if projection == "pattern_group":
            return _pattern_group(records)
        if projection == "series_hourly":
            return _series_hourly(records)
        return _rows_dataset(records)


def _rows_dataset(records: Sequence[LogRecord]) -> DataSet:
    columns = ("at", "severity", "body", "labels")
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "at": r.at.isoformat(),
                "severity": r.severity,
                "body": r.body,
                "labels": dict(r.labels),
            }
            for r in records
        ),
    )


def _count_by_severity(records: Sequence[LogRecord]) -> DataSet:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.severity] = counts.get(record.severity, 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    return DataSet(
        columns=("severity", "value"),
        rows=tuple({"severity": k, "value": v, "label": k} for k, v in ordered),
    )


def _as_mapping(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    return {}


def _pattern_group(records: Sequence[LogRecord]) -> DataSet:
    """Naive log clustering: bucket by leading token of each body.

    Real clustering is a T1 job (embedding similarity); this projection
    exists so a fork with no clustering wired can still surface a
    "top-N noisy patterns" table. A row shape is
    ``{"pattern", "sample", "value"}``.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        head = record.body.strip().split(" ", 1)[0][:64] or "(empty)"
        entry = buckets.setdefault(head, {"pattern": head, "sample": record.body, "value": 0})
        entry["value"] = int(entry["value"]) + 1
    rows = sorted(buckets.values(), key=lambda r: r["value"], reverse=True)
    return DataSet(
        columns=("pattern", "sample", "value"),
        rows=tuple(rows),
        metadata={"pattern_count": len(rows)},
    )


def _series_hourly(records: Sequence[LogRecord]) -> DataSet:
    """Count log records by hourly bucket - a single series result."""
    from fdai.core.reporting.models import Series

    buckets: dict[str, int] = {}
    for record in records:
        key_dt = record.at.replace(minute=0, second=0, microsecond=0)
        stamp = key_dt.isoformat()
        buckets[stamp] = buckets.get(stamp, 0) + 1
    ordered = sorted(buckets.items())
    from datetime import datetime as _dt

    points = tuple((_dt.fromisoformat(k).timestamp(), float(v)) for k, v in ordered)
    return DataSet(
        series=(Series(label="count_hourly", points=points),),
        metadata={"bucket": "hour", "count": len(ordered)},
    )


__all__ = ["LogQueryDataSource"]
