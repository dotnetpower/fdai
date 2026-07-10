"""Flow-family widget builders: funnel, sankey, treemap.

These widgets share a "topology + weights" shape: nodes / stages /
tiles with numeric weights. Every one is a pure transform over
:attr:`~fdai.core.reporting.models.DataSet.rows`.

Widget ``data`` schemas:

- ``funnel``: ``{"stages": [{"label", "value"}]}`` in the order rows
  arrive; each ``conversion_ratio`` (relative to the first stage) is
  attached alongside the raw value.
- ``sankey``: ``{"nodes": [{"id"}], "links": [{"source", "target",
  "value"}]}``.
- ``treemap``: ``{"tiles": [{"label", "value", "group"?}]}`` sorted by
  value descending.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.models import DataSet, WidgetSpec


class FunnelBuilder:
    """Render ordered rows as funnel stages with conversion ratios."""

    type_name = "funnel"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        label_field = str(spec.options.get("label_field", "stage"))
        value_field = str(spec.options.get("value_field", "value"))
        stages = []
        first_value: float | None = None
        for row in data.rows:
            label = row.get(label_field)
            raw_value = row.get(value_field)
            value = _numeric_or_none(raw_value)
            if value is None:
                stages.append({"label": label, "value": None, "conversion_ratio": None})
                continue
            if first_value is None:
                first_value = value
                ratio: float | None = 1.0
            elif first_value == 0:
                ratio = None
            else:
                ratio = value / first_value
            stages.append({"label": label, "value": value, "conversion_ratio": ratio})
        return {"stages": stages}


class SankeyBuilder:
    """Render source/target/value rows as a Sankey graph.

    Node ids are the union of every source and target seen. Duplicate
    ``(source, target)`` links are summed so the FE sees one edge per
    pair.
    """

    type_name = "sankey"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        source_field = str(spec.options.get("source_field", "source"))
        target_field = str(spec.options.get("target_field", "target"))
        value_field = str(spec.options.get("value_field", "value"))
        seen_nodes: dict[str, None] = {}
        totals: dict[tuple[str, str], float] = {}
        for row in data.rows:
            source = row.get(source_field)
            target = row.get(target_field)
            value = _numeric_or_none(row.get(value_field))
            if source is None or target is None or value is None:
                continue
            source_id = str(source)
            target_id = str(target)
            seen_nodes[source_id] = None
            seen_nodes[target_id] = None
            key = (source_id, target_id)
            totals[key] = totals.get(key, 0.0) + float(value)
        return {
            "nodes": [{"id": node_id} for node_id in seen_nodes],
            "links": [
                {"source": src, "target": tgt, "value": total}
                for (src, tgt), total in totals.items()
            ],
        }


class TreemapBuilder:
    """Render rows as area-weighted tiles sorted by value descending."""

    type_name = "treemap"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        label_field = str(spec.options.get("label_field", "label"))
        value_field = str(spec.options.get("value_field", "value"))
        group_field = spec.options.get("group_field")
        tiles = []
        for row in data.rows:
            value = _numeric_or_none(row.get(value_field))
            if value is None:
                continue
            tile: dict[str, Any] = {
                "label": row.get(label_field),
                "value": value,
            }
            if group_field and group_field in row:
                tile["group"] = row.get(group_field)
            tiles.append(tile)
        tiles.sort(key=lambda t: float(t["value"]), reverse=True)
        return {"tiles": tiles}


def _numeric_or_none(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "FunnelBuilder",
    "SankeyBuilder",
    "TreemapBuilder",
]
