"""Report-feed datasource - wraps ``core.report_feed.ReportFeed``.

Projects the aggregated signal list into report shapes:

- ``"rows"`` (default) -> table / list_stream: one row per signal with
  ``signal_id / kind / category / severity / resource_ref / title /
  detail / occurred_at``.
- ``"count_by_severity"`` -> table / bar_chart: one row per severity.
- ``"count_by_category"`` -> table / bar_chart: one row per category.
- ``"count_by_kind"`` -> top_list / bar_chart: one row per signal kind.
- ``"count_total"`` -> query_value: total signal count.

Query parameters:

- ``category`` (str, optional): one of ``workload`` / ``security`` to
  narrow the feed at the source. Invalid values fall through as ``None``.
- ``projection`` (str, default ``rows``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from fdai.core.report_feed.feed import ReportFeed
from fdai.core.report_feed.models import ReportCategory, ReportSignal
from fdai.core.reporting.models import DataSet, QuerySpec


class ReportFeedDataSource:
    """Projection over :class:`~fdai.core.report_feed.feed.ReportFeed`."""

    __slots__ = ("_name", "_feed")

    def __init__(self, *, feed: ReportFeed, name: str = "report_feed") -> None:
        self._name = name
        self._feed = feed

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
        category = _resolve_category(spec.parameters.get("category"))
        projection = str(spec.parameters.get("projection", "rows"))
        result = await self._feed.collect(since=since, until=until, category=category)
        signals = result.signals
        metadata: dict[str, object] = {
            "source_errors": [f"{name}:{err}" for name, err in result.source_errors],
        }

        if projection == "rows":
            return _rows_dataset(signals, metadata=metadata)
        if projection == "count_by_severity":
            return _count_by_dataset(
                signals, key=lambda s: s.severity.value, label="severity", metadata=metadata
            )
        if projection == "count_by_category":
            return _count_by_dataset(
                signals, key=lambda s: s.category.value, label="category", metadata=metadata
            )
        if projection == "count_by_kind":
            return _count_by_dataset(
                signals, key=lambda s: s.kind.value, label="kind", metadata=metadata
            )
        if projection == "count_total":
            return DataSet(scalar=len(signals), metadata=metadata)
        metadata["unknown_projection"] = projection
        return DataSet(metadata=metadata)


def _resolve_category(raw: object) -> ReportCategory | None:
    if raw is None:
        return None
    try:
        return ReportCategory(str(raw))
    except ValueError:
        return None


def _rows_dataset(signals: Sequence[ReportSignal], *, metadata: Mapping[str, object]) -> DataSet:
    return DataSet(
        columns=(
            "signal_id",
            "kind",
            "category",
            "severity",
            "resource_ref",
            "title",
            "detail",
            "at",
        ),
        rows=tuple(
            {
                "signal_id": s.signal_id,
                "kind": s.kind.value,
                "category": s.category.value,
                "severity": s.severity.value,
                "resource_ref": s.resource_ref,
                "title": s.title,
                "detail": s.detail,
                "at": s.occurred_at.isoformat(),
            }
            for s in signals
        ),
        metadata=dict(metadata),
    )


def _count_by_dataset(
    signals: Sequence[ReportSignal],
    *,
    key: Callable[[ReportSignal], object],
    label: str,
    metadata: Mapping[str, object],
) -> DataSet:
    counts: dict[str, int] = {}
    for signal in signals:
        bucket = str(key(signal))
        counts[bucket] = counts.get(bucket, 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    return DataSet(
        columns=(label, "value"),
        rows=tuple({label: k, "value": v, "label": k} for k, v in ordered),
        metadata=dict(metadata),
    )


__all__ = ["ReportFeedDataSource"]
