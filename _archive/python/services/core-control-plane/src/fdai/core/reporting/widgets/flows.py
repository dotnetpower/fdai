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

import math
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

    Sankey diagrams are strictly acyclic (they are flow diagrams);
    ``d3-sankey`` and every mainstream FE library throw on a cycle.
    Two guards keep an operator-supplied dataset from breaking the
    console render:

    - Self-loops (``source == target``) are dropped - a link from a node
      to itself is meaningless in a flow graph.
    - Cycle-closing edges are dropped in the order they arrive. Links
      are appended to a growing DAG; a link that would introduce a path
      back to its source is skipped. The first observed direction of a
      pair wins, so a legitimate DAG passes through untouched.
    """

    type_name = "sankey"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        source_field = str(spec.options.get("source_field", "source"))
        target_field = str(spec.options.get("target_field", "target"))
        value_field = str(spec.options.get("value_field", "value"))
        seen_nodes: dict[str, None] = {}
        totals: dict[tuple[str, str], float] = {}
        # Adjacency map used to detect a cycle-closing edge before we
        # accept it into ``totals``. Kept in insertion order so a run of
        # duplicate ``(source, target)`` rows only sums against the
        # already-accepted direction and never flips it.
        accepted_out: dict[str, set[str]] = {}
        for row in data.rows:
            source = row.get(source_field)
            target = row.get(target_field)
            value = _numeric_or_none(row.get(value_field))
            if source is None or target is None or value is None:
                continue
            source_id = str(source)
            target_id = str(target)
            if source_id == target_id:
                # Self-loop: meaningless in a flow graph and breaks
                # d3-sankey. Drop silently.
                continue
            key = (source_id, target_id)
            if key not in totals and _would_close_sankey_cycle(source_id, target_id, accepted_out):
                # A path already exists from target back to source; adding
                # source -> target would close a cycle. Drop the new
                # direction and keep the earlier one.
                continue
            seen_nodes[source_id] = None
            seen_nodes[target_id] = None
            totals[key] = totals.get(key, 0.0) + float(value)
            accepted_out.setdefault(source_id, set()).add(target_id)
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
        return value if math.isfinite(value) else None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # Reject 'nan' / 'inf' strings: a non-finite weight breaks funnel
    # ratios / treemap sort and serializes to invalid JSON.
    return result if math.isfinite(result) else None


def _would_close_sankey_cycle(
    source: str, target: str, accepted_out: Mapping[str, set[str]]
) -> bool:
    """True when adding ``source -> target`` would form a cycle.

    Walks the accepted DAG forward from ``target``; if it can reach
    ``source`` (or revisits a node, which itself proves an earlier cycle
    slipped through), the new edge closes a loop and MUST be dropped.
    Iterative, bounded by the visited set, so a large or deep graph
    cannot recurse the stack.
    """
    if target == source:
        return True
    seen: set[str] = set()
    stack: list[str] = [target]
    while stack:
        node = stack.pop()
        if node == source:
            return True
        if node in seen:
            continue
        seen.add(node)
        successors = accepted_out.get(node)
        if successors:
            stack.extend(successors)
    return False


class RetentionBuilder:
    """Cohort retention grid.

    Expects rows shaped ``{"cohort", "period", "value"}``. Groups by
    cohort and produces one row per cohort with a period-indexed value
    list. The FE renders the triangle grid. Field names overridable via
    ``options``.
    """

    type_name = "retention"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        cohort_field = str(spec.options.get("cohort_field", "cohort"))
        period_field = str(spec.options.get("period_field", "period"))
        value_field = str(spec.options.get("value_field", "value"))
        by_cohort: dict[str, dict[Any, Any]] = {}
        periods: set[Any] = set()
        for row in data.rows:
            cohort = row.get(cohort_field)
            period = row.get(period_field)
            value = row.get(value_field)
            if cohort is None or period is None:
                continue
            periods.add(period)
            by_cohort.setdefault(str(cohort), {})[period] = value
        ordered_periods = sorted(periods, key=lambda p: (isinstance(p, str), p))
        rows: list[dict[str, Any]] = []
        for cohort_name in sorted(by_cohort):
            rows.append(
                {
                    "cohort": cohort_name,
                    "values": [by_cohort[cohort_name].get(p) for p in ordered_periods],
                }
            )
        return {"periods": ordered_periods, "rows": rows}


__all__ = [
    "FunnelBuilder",
    "RetentionBuilder",
    "SankeyBuilder",
    "TreemapBuilder",
]
