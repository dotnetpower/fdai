"""Batch-6 hardening: widget-builder robustness against hostile datasource
values (non-finite numbers, cyclic flame graphs, epoch timestamps, etc.).

Each test maps to one hardening item H1-H10 from the reporting critique.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from fdai.core.reporting.formats import JsonFormatEncoder
from fdai.core.reporting.models import (
    DataSet,
    RenderedReport,
    RenderedWidget,
    Series,
    WidgetSpec,
)
from fdai.core.reporting.widgets.cost import BudgetSummaryBuilder, CostSummaryBuilder
from fdai.core.reporting.widgets.flows import (
    FunnelBuilder,
    SankeyBuilder,
    TreemapBuilder,
)
from fdai.core.reporting.widgets.graphs import (
    GaugeBuilder,
    PieChartBuilder,
    SparklineBuilder,
)
from fdai.core.reporting.widgets.lists import (
    EventStreamBuilder,
    ListStreamBuilder,
    TopListBuilder,
)
from fdai.core.reporting.widgets.reliability import FlameGraphBuilder

_SPEC = WidgetSpec(id="w", type="x", title="t")


def _spec(**options: object) -> WidgetSpec:
    return WidgetSpec(id="w", type="x", title="t", options=options)


# --- H1: JSON encoder rewrites non-finite floats to null -----------------


def test_h1_json_encoder_sanitizes_non_finite() -> None:
    report = RenderedReport(
        id="r",
        version="1",
        name="n",
        description="d",
        generated_at=datetime(2026, 7, 10, tzinfo=UTC),
        time_range=(datetime(2026, 7, 10, tzinfo=UTC), datetime(2026, 7, 10, tzinfo=UTC)),
        variables={},
        widgets=(
            RenderedWidget(
                id="w",
                type="query_value",
                title="t",
                data={"value": float("nan"), "nested": [float("inf"), 1.5, float("-inf")]},
            ),
        ),
    )
    body = JsonFormatEncoder().encode(report)
    # Must be strict-valid JSON (no bare NaN/Infinity tokens).
    assert b"NaN" not in body
    assert b"Infinity" not in body
    parsed = json.loads(body)
    data = parsed["widgets"][0]["data"]
    assert data["value"] is None
    assert data["nested"] == [None, 1.5, None]


# --- H2: flame graph never builds a cyclic (unserializable) structure ----


def test_h2_flame_graph_breaks_cycles() -> None:
    data = DataSet(
        rows=(
            {"name": "a", "value": 1, "parent": "b"},
            {"name": "b", "value": 1, "parent": "a"},  # a<->b cycle
            {"name": "c", "value": 1, "parent": "c"},  # self-parent
        )
    )
    out = FlameGraphBuilder().build(spec=_SPEC, data=data)
    # The whole point: the result serializes without a circular-ref error.
    json.dumps(out)
    assert "roots" in out
    # c is a self-parent -> the self edge is dropped, so c is a root.
    root_names = {n["name"] for n in out["roots"]}
    assert "c" in root_names


def test_h2_flame_graph_normal_tree_still_works() -> None:
    data = DataSet(
        rows=(
            {"name": "root", "value": 10, "parent": None},
            {"name": "child", "value": 4, "parent": "root"},
        )
    )
    out = FlameGraphBuilder().build(spec=_SPEC, data=data)
    json.dumps(out)
    assert [n["name"] for n in out["roots"]] == ["root"]
    assert out["roots"][0]["children"][0]["name"] == "child"


# --- H3: graph numeric coercion rejects non-finite -----------------------


def test_h3_gauge_rejects_nan_scalar() -> None:
    out = GaugeBuilder().build(spec=_spec(min=0, max=100), data=DataSet(scalar=float("nan")))
    assert out["value"] is None
    assert out["ratio"] is None


# --- H4: cost coercion rejects non-finite (string + float) ---------------


def test_h4_cost_summary_drops_non_finite_amounts() -> None:
    data = DataSet(rows=({"group": "a", "amount": "inf"}, {"group": "b", "amount": 5}))
    out = CostSummaryBuilder().build(spec=_SPEC, data=data)
    assert out["total"] == 5.0
    assert math.isfinite(out["total"])


def test_h4_budget_summary_nan_actual_is_zero() -> None:
    out = BudgetSummaryBuilder().build(spec=_spec(budget=100), data=DataSet(scalar=float("nan")))
    assert out["actual"] == 0.0


# --- H5: flow coercion rejects non-finite --------------------------------


def test_h5_funnel_drops_non_finite() -> None:
    data = DataSet(rows=({"stage": "s1", "value": "nan"}, {"stage": "s2", "value": 10}))
    out = FunnelBuilder().build(spec=_SPEC, data=data)
    assert out["stages"][0]["value"] is None
    assert out["stages"][1]["value"] == 10


def test_h5_treemap_sort_stable_without_non_finite() -> None:
    data = DataSet(rows=({"label": "a", "value": "inf"}, {"label": "b", "value": 3}))
    out = TreemapBuilder().build(spec=_SPEC, data=data)
    # inf is dropped, only b remains.
    assert [t["label"] for t in out["tiles"]] == ["b"]


# --- H6: top_list sort deterministic with non-finite rank ----------------


def test_h6_top_list_nan_rank_sorts_to_bottom() -> None:
    data = DataSet(
        rows=(
            {"label": "hi", "value": 100},
            {"label": "bad", "value": float("nan")},
            {"label": "mid", "value": 50},
        )
    )
    out = TopListBuilder().build(spec=_spec(rank_by="value", order="desc"), data=data)
    labels = [r["label"] for r in out["rows"]]
    assert labels[0] == "hi"
    assert labels[-1] == "bad"


# --- H7: sparkline finite-safe min/max/last ------------------------------


def test_h7_sparkline_ignores_non_finite_points() -> None:
    series = Series(
        label="s",
        points=((1.0, 3.0), (2.0, float("nan")), (3.0, 7.0), (4.0, float("inf"))),
    )
    out = SparklineBuilder().build(spec=_SPEC, data=DataSet(series=(series,)))
    s = out["series"][0]
    assert s["min"] == 3.0
    assert s["max"] == 7.0
    assert s["last"] == 7.0
    assert all(math.isfinite(v) for v in s["values"])


def test_h7_sparkline_all_bad_points_is_none() -> None:
    series = Series(label="s", points=((1.0, float("nan")),))
    out = SparklineBuilder().build(spec=_SPEC, data=DataSet(series=(series,)))
    s = out["series"][0]
    assert s["min"] is None and s["max"] is None and s["last"] is None


# --- H8: stream timestamp sort is numeric-aware --------------------------


def test_h8_list_stream_epoch_int_sort_is_numeric() -> None:
    data = DataSet(
        rows=(
            {"at": 9, "msg": "old"},
            {"at": 100, "msg": "new"},
            {"at": 30, "msg": "mid"},
        )
    )
    out = ListStreamBuilder().build(spec=_SPEC, data=data)
    order = [r["at"] for r in out["items"]]
    assert order == [100, 30, 9]  # newest (largest epoch) first, numerically


def test_h8_event_stream_epoch_int_sort_is_numeric() -> None:
    data = DataSet(
        rows=(
            {"at": 9, "severity": "low"},
            {"at": 100, "severity": "critical"},
        )
    )
    out = EventStreamBuilder().build(spec=_SPEC, data=data)
    assert [r["at"] for r in out["items"]] == [100, 9]
    assert out["counts_by_severity"]["critical"] == 1


# --- H9: pie percent from magnitude, not signed sum ----------------------


def test_h9_pie_percent_uses_magnitude() -> None:
    data = DataSet(rows=({"label": "a", "value": 3}, {"label": "b", "value": -1}))
    out = PieChartBuilder().build(spec=_SPEC, data=data)
    percents = {s["label"]: s["percent"] for s in out["slices"]}
    # magnitude total = 3 + 1 = 4 -> a=0.75, b=0.25; no percent > 1.
    assert percents["a"] == 0.75
    assert percents["b"] == 0.25
    assert all(0.0 <= s["percent"] <= 1.0 for s in out["slices"])


def test_h9_pie_skips_non_finite() -> None:
    data = DataSet(rows=({"label": "a", "value": float("inf")}, {"label": "b", "value": 2}))
    out = PieChartBuilder().build(spec=_SPEC, data=data)
    assert [s["label"] for s in out["slices"]] == ["b"]


# --- H10: __all__ placement exports late-defined builders ----------------


def test_h10_all_exports_late_defined_builders() -> None:
    from fdai.core.reporting.widgets import flows, lists

    assert "EventStreamBuilder" in lists.__all__
    assert hasattr(lists, "EventStreamBuilder")
    assert "RetentionBuilder" in flows.__all__
    assert hasattr(flows, "RetentionBuilder")


# --- H11: Sankey drops cycle-closing links and self-loops ----------------
# Same failure class as H2 (flame graph): d3-sankey throws on any cycle,
# so a cyclic source->target dataset would silently break the console
# render. Batch-6 hardened flame_graph but missed the equivalent guard
# on SankeyBuilder.


def test_h11_sankey_drops_self_loop_link() -> None:
    data = DataSet(
        rows=(
            {"source": "a", "target": "a", "value": 1},  # self-loop
            {"source": "a", "target": "b", "value": 2},
        )
    )
    out = SankeyBuilder().build(spec=_SPEC, data=data)
    # Self-loop removed; only the honest a->b link survives.
    assert [(link["source"], link["target"]) for link in out["links"]] == [("a", "b")]
    # Node 'a' is still there (it participates in the surviving link).
    assert {n["id"] for n in out["nodes"]} == {"a", "b"}


def test_h11_sankey_drops_cycle_closing_link_keeps_first_direction() -> None:
    data = DataSet(
        rows=(
            {"source": "a", "target": "b", "value": 1},
            {"source": "b", "target": "c", "value": 2},
            {"source": "c", "target": "a", "value": 3},  # closes a->b->c->a
        )
    )
    out = SankeyBuilder().build(spec=_SPEC, data=data)
    pairs = {(link["source"], link["target"]) for link in out["links"]}
    # a->b and b->c stay; c->a is dropped so the graph remains a DAG.
    assert ("a", "b") in pairs
    assert ("b", "c") in pairs
    assert ("c", "a") not in pairs
    # Nodes 'a' and 'b' and 'c' are all present via the surviving links.
    assert {n["id"] for n in out["nodes"]} == {"a", "b", "c"}


def test_h11_sankey_two_node_flip_drops_reverse_link() -> None:
    """A direct back-edge (b->a after a->b) is a cycle and MUST be dropped."""
    data = DataSet(
        rows=(
            {"source": "a", "target": "b", "value": 1},
            {"source": "b", "target": "a", "value": 5},  # closes a<->b
        )
    )
    out = SankeyBuilder().build(spec=_SPEC, data=data)
    pairs = {(link["source"], link["target"]) for link in out["links"]}
    assert pairs == {("a", "b")}


def test_h11_sankey_repeated_forward_pair_still_sums() -> None:
    """Cycle guard must not break the existing dedup-and-sum behavior."""
    data = DataSet(
        rows=(
            {"source": "a", "target": "b", "value": 1},
            {"source": "a", "target": "b", "value": 2},
            {"source": "b", "target": "c", "value": 4},
        )
    )
    out = SankeyBuilder().build(spec=_SPEC, data=data)
    by_pair = {(link["source"], link["target"]): link["value"] for link in out["links"]}
    assert by_pair[("a", "b")] == 3.0
    assert by_pair[("b", "c")] == 4.0


def test_h11_sankey_diamond_dag_survives_intact() -> None:
    """A legitimate DAG (diamond a->b, a->c, b->d, c->d) is untouched."""
    data = DataSet(
        rows=(
            {"source": "a", "target": "b", "value": 1},
            {"source": "a", "target": "c", "value": 1},
            {"source": "b", "target": "d", "value": 1},
            {"source": "c", "target": "d", "value": 1},
        )
    )
    out = SankeyBuilder().build(spec=_SPEC, data=data)
    pairs = {(link["source"], link["target"]) for link in out["links"]}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")}
