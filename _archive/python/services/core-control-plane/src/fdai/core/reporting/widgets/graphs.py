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

import math
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


class PieChartBuilder:
    """Render categorical rows as pie slices with pre-computed percentages."""

    type_name = "pie_chart"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        label_field = str(spec.options.get("label_field", "label"))
        value_field = str(spec.options.get("value_field", "value"))
        slices: list[dict[str, Any]] = []
        magnitude_total = 0.0
        signed_total = 0.0
        for row in data.rows:
            value = _as_number(row.get(value_field))
            if value is None:
                continue
            slices.append({"label": row.get(label_field), "value": value})
            magnitude_total += abs(float(value))
            signed_total += float(value)
        # Percent is derived from magnitude, not the signed sum, so a
        # negative or mixed-sign dataset cannot produce a percent > 1 or a
        # divide-by-(near-zero-)signed-total artifact.
        for entry in slices:
            entry["percent"] = (
                (abs(float(entry["value"])) / magnitude_total) if magnitude_total > 0 else 0.0
            )
        return {"slices": slices, "total": signed_total}


class ScatterPlotBuilder:
    """Render rows as (x, y) points, optionally colored by a group label."""

    type_name = "scatter_plot"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        x_field = str(spec.options.get("x_field", "x"))
        y_field = str(spec.options.get("y_field", "y"))
        group_field = spec.options.get("group_field")
        points: list[dict[str, Any]] = []
        for row in data.rows:
            x = _as_number(row.get(x_field))
            y = _as_number(row.get(y_field))
            if x is None or y is None:
                continue
            point: dict[str, Any] = {"x": x, "y": y}
            if group_field and group_field in row:
                point["group"] = row.get(group_field)
            points.append(point)
        return {"points": points}


class SparklineBuilder:
    """Compact inline series - one value per point per series."""

    type_name = "sparkline"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del spec
        series = []
        for s in data.series:
            # Only finite numeric values feed min/max/last: a None or a
            # non-numeric point would raise TypeError under min()/max(),
            # and a NaN/Inf would poison the summary + JSON. Filtering
            # keeps a partially-bad series renderable instead of erroring.
            values = [v for v in (_as_number(p[1]) for p in s.points) if v is not None]
            series.append(
                {
                    "label": s.label,
                    "values": values,
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                    "last": values[-1] if values else None,
                }
            )
        return {"series": series}


class GaugeBuilder:
    """Needle gauge from ``value`` + ``options.min`` + ``options.max``."""

    type_name = "gauge"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        value = _as_number(data.scalar)
        low = _as_number(spec.options.get("min"))
        low_v = 0.0 if low is None else float(low)
        high = _as_number(spec.options.get("max"))
        high_v = 100.0 if high is None else float(high)
        ratio: float | None = None
        if value is not None and high_v != low_v:
            ratio = max(0.0, min(1.0, (float(value) - low_v) / (high_v - low_v)))
        return {
            "value": value,
            "min": low_v,
            "max": high_v,
            "ratio": ratio,
            "unit": spec.options.get("unit"),
        }


class ProgressBarBuilder:
    """Horizontal progress bar (current vs. target); ratio clamped [0, 1]."""

    type_name = "progress_bar"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        current_raw = _as_number(data.scalar)
        current = 0.0 if current_raw is None else float(current_raw)
        target_raw = _as_number(spec.options.get("target"))
        target = 0.0 if target_raw is None else float(target_raw)
        ratio: float | None
        if target == 0:
            ratio = None
        else:
            ratio = max(0.0, min(1.0, current / target))
        return {
            "current": current,
            "target": target,
            "ratio": ratio,
            "unit": spec.options.get("unit"),
        }


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
        # Reject NaN / +-Inf: they poison sums and serialize to invalid
        # JSON (RFC 8259 has no NaN/Infinity token).
        return value if math.isfinite(value) else None
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
    "GaugeBuilder",
    "HeatmapBuilder",
    "PieChartBuilder",
    "ProgressBarBuilder",
    "QueryValueBuilder",
    "ScatterPlotBuilder",
    "SparklineBuilder",
    "TimeseriesBuilder",
]
