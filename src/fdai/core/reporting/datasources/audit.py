"""Audit-log datasource - projects an audit reader into report shapes.

The upstream ``ConsoleReadModel`` (``delivery/read_api/read_model.py``)
already exposes ``list_audit`` returning
:class:`~fdai.delivery.read_api.read_model.AuditPage`; this datasource
consumes anything that structurally matches - a narrow duck-typed
:class:`AuditReader` Protocol - so ``core/`` never imports
``delivery/``.

Query parameters (``spec.parameters``):

- ``projection`` (str, required): one of the projections listed below.
- ``limit`` (int, optional): max audit rows to fetch (bounded by the
  underlying reader).
- ``since`` / ``until``: automatically forwarded from the report time
  range - the datasource filters rows on ``recorded_at`` before running
  the projection.

Projections:

- ``"rows"`` -> table / list_stream: raw audit rows shaped as
  ``{seq, event_id, correlation_id, actor, action_kind, mode, at}``.
- ``"count_by_action_kind"`` -> table / top_list / bar_chart: one row
  per ``action_kind`` with ``count``.
- ``"count_by_mode"`` -> table / bar_chart: one row per mode
  (``shadow`` / ``enforce``).
- ``"count_total"`` -> query_value: single scalar row count.
- ``"count_by_actor"`` -> top_list: rows shaped ``{actor, count}``.

Every projection is read-only; the datasource never mutates the reader.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from fdai.core.reporting.models import DataSet, QuerySpec

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000


@runtime_checkable
class AuditRow(Protocol):
    """Duck-typed audit row (matches ``read_api.AuditItem``)."""

    seq: int
    event_id: str
    correlation_id: str | None
    actor: str
    action_kind: str
    mode: str
    recorded_at: str


@runtime_checkable
class AuditPage(Protocol):
    """Duck-typed audit page (matches ``read_api.AuditPage``)."""

    items: Sequence[AuditRow]
    next_cursor: str | None


@runtime_checkable
class AuditReader(Protocol):
    """Narrow duck-typed reader; ``ConsoleReadModel`` satisfies it."""

    async def list_audit(
        self,
        *,
        limit: int = ...,
        cursor: str | None = ...,
    ) -> AuditPage: ...


class AuditDataSource:
    """Project audit rows into report shapes.

    Time-range filtering is done in Python on the returned page (the
    upstream reader has no `since`/`until` argument); a fork with a
    Postgres-backed reader can bind a wider Protocol later without
    changing this datasource.
    """

    __slots__ = ("_name", "_reader")

    def __init__(self, *, reader: AuditReader, name: str = "audit") -> None:
        self._name = name
        self._reader = reader

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
        projection = str(spec.parameters.get("projection", "rows"))
        limit = _clamp(spec.parameters.get("limit"))
        page = await self._reader.list_audit(limit=limit)
        rows = _in_window(page.items, since=since, until=until)

        if projection == "rows":
            return _rows_dataset(rows)
        if projection == "count_by_action_kind":
            return _count_by_dataset(rows, key="action_kind", label="action_kind")
        if projection == "count_by_mode":
            return _count_by_dataset(rows, key="mode", label="mode")
        if projection == "count_by_actor":
            return _count_by_dataset(rows, key="actor", label="actor")
        if projection == "count_by_correlation":
            return _count_by_correlation(rows)
        if projection == "series_hourly":
            return _series_bucket(rows, bucket="hour")
        if projection == "series_daily":
            return _series_bucket(rows, bucket="day")
        if projection == "count_total":
            return DataSet(scalar=len(rows), metadata={"projection": projection})
        return DataSet(metadata={"unknown_projection": projection})


def _clamp(raw: Any) -> int:
    try:
        value = int(raw) if raw is not None else _DEFAULT_LIMIT
    except (TypeError, ValueError):
        value = _DEFAULT_LIMIT
    if value < 1:
        return 1
    if value > _MAX_LIMIT:
        return _MAX_LIMIT
    return value


def _in_window(
    items: Sequence[AuditRow], *, since: datetime, until: datetime
) -> tuple[AuditRow, ...]:
    """Filter rows to those whose ``recorded_at`` falls in ``[since, until]``.

    ``recorded_at`` is the audit-log ISO-8601 string. Compared as
    tz-aware :class:`datetime` values so a naive vs aware mismatch
    cannot silently exclude legitimate rows; a row whose timestamp
    cannot be parsed is included (fail-open toward preservation - audit
    records should never be dropped just because their format drifted).
    """
    since_utc = _to_utc(since)
    until_utc = _to_utc(until)
    kept: list[AuditRow] = []
    for row in items:
        row_at = _parse_iso(row.recorded_at)
        if row_at is None:
            kept.append(row)
            continue
        if since_utc <= row_at <= until_utc:
            kept.append(row)
    return tuple(kept)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _to_utc(parsed)


def _rows_dataset(rows: Sequence[AuditRow]) -> DataSet:
    columns = (
        "seq",
        "event_id",
        "correlation_id",
        "actor",
        "action_kind",
        "mode",
        "at",
    )
    return DataSet(
        columns=columns,
        rows=tuple(
            {
                "seq": row.seq,
                "event_id": row.event_id,
                "correlation_id": row.correlation_id,
                "actor": row.actor,
                "action_kind": row.action_kind,
                "mode": row.mode,
                "at": row.recorded_at,
            }
            for row in rows
        ),
    )


def _count_by_dataset(rows: Sequence[AuditRow], *, key: str, label: str) -> DataSet:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(getattr(row, key, ""))
        counts[value] = counts.get(value, 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    return DataSet(
        columns=(label, "value"),
        rows=tuple({label: k, "value": v, "label": k} for k, v in ordered),
    )


def _count_by_correlation(rows: Sequence[AuditRow]) -> DataSet:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.correlation_id or "(none)"
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    return DataSet(
        columns=("correlation_id", "value"),
        rows=tuple(
            {"correlation_id": k, "value": v, "label": k} for k, v in ordered
        ),
    )


def _series_bucket(rows: Sequence[AuditRow], *, bucket: str) -> DataSet:
    """Bucket audit rows into hourly / daily counts as a single series."""
    from fdai.core.reporting.models import Series

    buckets: dict[str, int] = {}
    for row in rows:
        parsed = _parse_iso(row.recorded_at)
        if parsed is None:
            continue
        if bucket == "hour":
            key_dt = parsed.replace(minute=0, second=0, microsecond=0)
        elif bucket == "day":
            key_dt = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            key_dt = parsed
        stamp = key_dt.isoformat()
        buckets[stamp] = buckets.get(stamp, 0) + 1
    ordered = sorted(buckets.items())
    points = tuple(
        (datetime.fromisoformat(k).timestamp(), float(v)) for k, v in ordered
    )
    return DataSet(
        series=(Series(label=f"count_{bucket}ly", points=points),),
        metadata={"bucket": bucket, "count": len(ordered)},
    )


__all__ = ["AuditDataSource", "AuditReader"]
