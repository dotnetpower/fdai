"""Graph-family widget builders: timeseries, query_value, change,
distribution, heatmap, bar_chart.

Each builder is a pure sync transform from a
:class:`~fdai.core.reporting.models.DataSet` to a widget-specific
``data`` mapping. The mappings follow a Datadog-inspired shape so the
FE renderer can key on ``type`` and read the same field names it uses
today.

Widget ``data`` schemas:

- ``timeseries``: ``{"series": [{"label", "labels", "points":
  [[epoch_seconds, value], ...]}]}``.
- ``query_value``: ``{"value": <number|str|null>, "unit"?, "precision"?}``.
- ``change``: ``{"current": <n>, "previous": <n>, "delta_absolute": <n>,
  "delta_ratio": <n|null>}``.
- ``distribution``: ``{"buckets": [{"le": <n>, "count": <n>}]}``.
- ``heatmap``: ``{"series": [...]}`` (same shape as timeseries; FE treats
  each series as one horizontal band).
- ``bar_chart``: ``{"bars": [{"label", "value"}]}``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec


class TimeseriesBuilder:
    """Render a :attr:`DataSet.series` as a stacked/multi-line time series."""

    type_name = "timeseries"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec  # unused
        return {
            "series": [
                {
                    "label": s.label,
                    "labels": dict(s.labels),
                    "points": [list(p) for p in s.points],
                }
                for s in data.series
            ]
        }


class QueryValueBuilder:
    """Render :attr:`DataSet.scalar` as a single big number.

    Falls back to the first row's first column if ``scalar`` is unset -
    so a datasource that returns a 1-row / 1-col table also works.
    """

    type_name = "query_value"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        value: Any = data.scalar
        if value is None and data.rows:
            first_row = data.rows[0]
            columns = data.columns or tuple(first_row.keys())
            if columns:
                value = first_row.get(columns[0])
        payload: dict[str, Any] = {"value": value}
        for opt_key in ("unit", "precision"):
            if opt_key in spec.options:
                payload[opt_key] = spec.options[opt_key]
        return payload


class ChangeBuilder:
    """Render the delta between two scalar samples.

    Expects the datasource to return two rows with a ``value`` column
    (previous first, current second) or a ``series`` with two points.
    Emits a fail-closed empty payload when neither is available.
    """

    type_name = "change"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        previous, current = _extract_pair(data)
        if previous is None or current is None:
            return {
                "current": current,
                "previous": previous,
                "delta_absolute": None,
                "delta_ratio": None,
            }
        delta_abs = current - previous
        delta_ratio = None if previous == 0 else delta_abs / previous
        return {
            "current": current,
            "previous": previous,
            "delta_absolute": delta_abs,
            "delta_ratio": delta_ratio,
        }


class DistributionBuilder:
    """Render a histogram-style breakdown.

    Expects rows shaped ``{"bucket": <upper-bound>, "count": <n>}`` (or
    the columns configured in ``options`` as ``bucket_field`` /
    ``count_field``). Sorts by bucket ascending.
    """

    type_name = "distribution"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        bucket_field = str(spec.options.get("bucket_field", "bucket"))
        count_field = str(spec.options.get("count_field", "count"))
        buckets = []
        for row in data.rows:
            if bucket_field not in row or count_field not in row:
                continue
            buckets.append(
                {
                    "le": row[bucket_field],
                    "count": row[count_field],
                }
            )
        buckets.sort(key=lambda b: _sortable(b["le"]))
        return {"buckets": buckets}


class HeatmapBuilder:
    """Render series as horizontal density bands.

    Same shape as :class:`TimeseriesBuilder` - the FE decides how to draw
    it. Keeping the payload identical means one datasource query can
    drive either widget without change.
    """

    type_name = "heatmap"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        return {
            "series": [
                {
                    "label": s.label,
                    "labels": dict(s.labels),
                    "points": [list(p) for p in s.points],
                }
                for s in data.series
            ]
        }


class BarChartBuilder:
    """Render categorical rows as a bar list.

    Expects rows with ``label`` / ``value`` columns (overridable via
    ``options.label_field`` / ``options.value_field``).
    """

    type_name = "bar_chart"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        label_field = str(spec.options.get("label_field", "label"))
        value_field = str(spec.options.get("value_field", "value"))
        bars = [{"label": row.get(label_field), "value": row.get(value_field)} for row in data.rows]
        return {"bars": bars}


def _extract_pair(data: DataSet) -> tuple[float | int | None, float | int | None]:
    """Return ``(previous, current)`` from either rows or a series."""
    if len(data.rows) >= 2:
        prev_val = data.rows[0].get("value")
        cur_val = data.rows[1].get("value")
        return _as_number(prev_val), _as_number(cur_val)
    if data.series and len(data.series[0].points) >= 2:
        points = data.series[0].points
        return _as_number(points[0][1]), _as_number(points[-1][1])
    return None, None


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _sortable(value: Any) -> tuple[int, Any]:
    """Push non-numeric bucket labels to the tail while keeping order stable."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value)
    return (1, str(value))


__all__ = [
    "BarChartBuilder",
    "ChangeBuilder",
    "DistributionBuilder",
    "HeatmapBuilder",
    "QueryValueBuilder",
    "TimeseriesBuilder",
]
