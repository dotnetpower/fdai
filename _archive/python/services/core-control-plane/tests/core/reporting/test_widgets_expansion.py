"""Smoke tests for the batch-6 widget expansion (19 new builders).

Each builder gets one shape-assertion test - the pattern is identical
across the family, so if the shape holds for a representative fixture
the FE contract holds too.
"""

from __future__ import annotations

from typing import Any

from fdai.core.reporting.models import DataSet, Series, WidgetSpec
from fdai.core.reporting.widgets import (
    AlertStatusBuilder,
    BudgetSummaryBuilder,
    CheckStatusBuilder,
    ComparisonBuilder,
    CostSummaryBuilder,
    EventStreamBuilder,
    FlameGraphBuilder,
    GaugeBuilder,
    GeomapBuilder,
    HostmapBuilder,
    IframeBuilder,
    ListStreamBuilder,
    PieChartBuilder,
    ProcessStepsBuilder,
    ProgressBarBuilder,
    RetentionBuilder,
    ScatterPlotBuilder,
    ServiceSummaryBuilder,
    SparklineBuilder,
    SplitGraphBuilder,
    TopListBuilder,
    TopologyMapBuilder,
    default_widget_builders,
)


def _spec(type_name: str, **options: Any) -> WidgetSpec:
    return WidgetSpec(id="w", type=type_name, title="t", options=options)


class TestGraphsExpansion:
    def test_pie_chart_percentages(self) -> None:
        data = DataSet(rows=({"label": "a", "value": 3}, {"label": "b", "value": 1}))
        result = PieChartBuilder().build(spec=_spec("pie_chart"), data=data)
        assert result["total"] == 4
        assert result["slices"][0]["percent"] == 0.75

    def test_scatter_plot_filters_incomplete_rows(self) -> None:
        data = DataSet(
            rows=(
                {"x": 1, "y": 2},
                {"x": 3},
                {"x": 5, "y": 4, "team": "ops"},
            )
        )
        result = ScatterPlotBuilder().build(
            spec=_spec("scatter_plot", group_field="team"),
            data=data,
        )
        assert len(result["points"]) == 2
        assert result["points"][1]["group"] == "ops"

    def test_sparkline_summary_stats(self) -> None:
        data = DataSet(series=(Series(label="a", points=((1.0, 5.0), (2.0, 10.0))),))
        result = SparklineBuilder().build(spec=_spec("sparkline"), data=data)
        assert result["series"][0]["last"] == 10.0
        assert result["series"][0]["max"] == 10.0

    def test_gauge_ratio(self) -> None:
        result = GaugeBuilder().build(
            spec=_spec("gauge", min=0, max=200),
            data=DataSet(scalar=50),
        )
        assert result["ratio"] == 0.25

    def test_progress_bar_ratio_clamped(self) -> None:
        result = ProgressBarBuilder().build(
            spec=_spec("progress_bar", target=10),
            data=DataSet(scalar=25),
        )
        assert result["ratio"] == 1.0


class TestListsExpansion:
    def test_event_stream_counts_by_severity(self) -> None:
        data = DataSet(
            rows=(
                {"at": "2026-01-02", "severity": "critical", "msg": "a"},
                {"at": "2026-01-03", "severity": "critical", "msg": "b"},
                {"at": "2026-01-01", "severity": "info", "msg": "c"},
            )
        )
        result = EventStreamBuilder().build(spec=_spec("event_stream"), data=data)
        assert result["counts_by_severity"]["critical"] == 2
        # Newest-first ordering by timestamp field.
        assert result["items"][0]["msg"] == "b"

    def test_event_stream_unknown_severity_folds_into_info(self) -> None:
        data = DataSet(
            rows=(
                {"at": "2026-01-02", "severity": "bogus", "msg": "a"},
                {"at": "2026-01-03", "msg": "b"},
            )
        )
        result = EventStreamBuilder().build(spec=_spec("event_stream"), data=data)
        # An unrecognized (or absent) severity is counted as 'info'.
        assert result["counts_by_severity"]["info"] == 2

    def test_top_list_numeric_guard_ranks_non_numeric_to_tail(self) -> None:
        # bool, NaN, Inf-string, and non-numeric strings all normalize to
        # -inf so they sink to the bottom of a desc ranking instead of
        # scrambling the sort; a real number ranks first.
        data = DataSet(
            rows=(
                {"name": "num", "value": 10},
                {"name": "flag", "value": True},
                {"name": "nan", "value": float("nan")},
                {"name": "infstr", "value": "inf"},
                {"name": "text", "value": "oops"},
            )
        )
        result = TopListBuilder().build(spec=_spec("top_list"), data=data)
        assert result["rows"][0]["name"] == "num"
        assert result["total_rows"] == 5


class TestWorkflowPresentation:
    def test_process_steps_normalizes_status_and_progress(self) -> None:
        result = ProcessStepsBuilder().build(
            spec=_spec("process_steps"),
            data=DataSet(
                rows=(
                    {"id": "collect", "name": "Collect", "status": "succeeded"},
                    {"id": "judge", "name": "Judge", "status": "running"},
                    {"id": "apply", "name": "Apply", "status": "unexpected"},
                )
            ),
        )
        assert result["completed"] == 1
        assert result["progress_ratio"] == 1 / 3
        assert result["steps"][2]["status"] == "unknown"

    def test_comparison_marks_changed_fields_without_judging_outcome(self) -> None:
        result = ComparisonBuilder().build(
            spec=_spec("comparison"),
            data=DataSet(
                rows=(
                    {"field": "replicas", "before": 2, "after": 4},
                    {"field": "region", "before": "a", "after": "a"},
                )
            ),
        )
        assert result["changed_count"] == 1
        assert result["rows"][0]["changed"] is True
        assert result["rows"][1]["changed"] is False

    def test_clamp_limit_handles_bad_zero_and_oversized(self) -> None:
        rows = tuple({"value": i} for i in range(30))

        def _n(limit: object) -> int:
            spec = _spec("top_list", limit=limit)
            return len(TopListBuilder().build(spec=spec, data=DataSet(rows=rows))["rows"])

        # Non-integer limit -> hard ceiling (all 30 rows fit under it).
        assert _n("abc") == 30
        # Zero clamps up to 1.
        assert _n(0) == 1
        # Oversized clamps down to the ceiling (>= 30, so all rows fit).
        assert _n(999999) == 30

    def test_list_stream_bool_timestamp_sorts_deterministically(self) -> None:
        # A boolean in the timestamp cell must not raise; it groups into
        # the non-numeric bucket rather than crashing the sort.
        data = DataSet(
            rows=(
                {"at": 100.0, "msg": "numeric"},
                {"at": True, "msg": "boolean"},
                {"at": "2026-01-01", "msg": "iso"},
            )
        )
        result = ListStreamBuilder().build(spec=_spec("list_stream"), data=data)
        assert result["total_rows"] == 3
        assert {item["msg"] for item in result["items"]} == {"numeric", "boolean", "iso"}


class TestFlowsExpansion:
    def test_retention_grid(self) -> None:
        data = DataSet(
            rows=(
                {"cohort": "c1", "period": 0, "value": 100},
                {"cohort": "c1", "period": 1, "value": 80},
                {"cohort": "c2", "period": 0, "value": 50},
            )
        )
        result = RetentionBuilder().build(spec=_spec("retention"), data=data)
        assert result["periods"] == [0, 1]
        by_cohort = {row["cohort"]: row["values"] for row in result["rows"]}
        assert by_cohort["c1"] == [100, 80]
        assert by_cohort["c2"] == [50, None]


class TestReliabilityExpansion:
    def test_alert_status_bucketed(self) -> None:
        data = DataSet(
            rows=(
                {"id": "a1", "severity": "critical", "title": "kv-01 exposed"},
                {"id": "a2", "severity": "low", "title": "noisy"},
            )
        )
        result = AlertStatusBuilder().build(spec=_spec("alert_status"), data=data)
        assert result["total"] == 2
        assert result["counts_by_severity"]["critical"] == 1

    def test_check_status_summary(self) -> None:
        data = DataSet(
            rows=(
                {"name": "db-ping", "status": "ok"},
                {"name": "kv-tls", "status": "fail"},
                {"name": "cache", "status": "WARN"},
            )
        )
        result = CheckStatusBuilder().build(spec=_spec("check_status"), data=data)
        assert result["summary"]["fail"] == 1
        assert result["summary"]["warn"] == 1

    def test_service_summary_normalizes_health(self) -> None:
        data = DataSet(
            rows=(
                {
                    "service": "web",
                    "requests_rps": 12.5,
                    "error_rate": 0.02,
                    "latency_p50": 30,
                    "latency_p99": 200,
                    "health": "DEGRADED",
                },
            )
        )
        result = ServiceSummaryBuilder().build(spec=_spec("service_summary"), data=data)
        assert result["health"] == "degraded"
        assert result["red"]["requests_rps"] == 12.5

    def test_flame_graph_nests_children(self) -> None:
        data = DataSet(
            rows=(
                {"name": "root", "value": 100},
                {"name": "child_a", "value": 40, "parent": "root"},
                {"name": "child_b", "value": 60, "parent": "root"},
                {"name": "grand", "value": 10, "parent": "child_a"},
            )
        )
        result = FlameGraphBuilder().build(spec=_spec("flame_graph"), data=data)
        assert len(result["roots"]) == 1
        root = result["roots"][0]
        assert {c["name"] for c in root["children"]} == {"child_a", "child_b"}


class TestArchitectureExpansion:
    def test_hostmap_carries_tiles(self) -> None:
        data = DataSet(
            rows=(
                {"host": "vm-01", "value": 0.8, "group": "prod"},
                {"host": "vm-02", "value": 0.4},
            )
        )
        result = HostmapBuilder().build(spec=_spec("hostmap"), data=data)
        assert result["tiles"][0]["group"] == "prod"

    def test_topology_map_splits_nodes_and_edges(self) -> None:
        data = DataSet(
            rows=(
                {"kind": "node", "id": "a", "label": "A"},
                {"kind": "node", "id": "b", "label": "B"},
                {"source": "a", "target": "b", "value": 3},
            )
        )
        result = TopologyMapBuilder().build(spec=_spec("topology_map"), data=data)
        assert {n["id"] for n in result["nodes"]} == {"a", "b"}
        assert result["edges"][0]["value"] == 3

    def test_geomap_splits_points_and_areas(self) -> None:
        data = DataSet(
            rows=(
                {"lat": 37.5, "lon": 127.0, "value": 12},
                {"region": "KR", "value": 100},
            )
        )
        result = GeomapBuilder().build(spec=_spec("geomap"), data=data)
        assert len(result["points"]) == 1
        assert result["areas"][0]["region"] == "KR"


class TestCostExpansion:
    def test_cost_summary_totals(self) -> None:
        data = DataSet(
            rows=(
                {"group": "compute", "amount": 100.0},
                {"group": "storage", "amount": 25.5},
            )
        )
        result = CostSummaryBuilder().build(spec=_spec("cost_summary", currency="USD"), data=data)
        assert result["total"] == 125.5
        assert result["currency"] == "USD"

    def test_budget_summary_variance(self) -> None:
        result = BudgetSummaryBuilder().build(
            spec=_spec("budget_summary", budget=100),
            data=DataSet(scalar=125),
        )
        assert result["variance"] == 25
        assert result["utilization"] == 1.25

    def test_budget_summary_reads_first_row_when_no_scalar(self) -> None:
        # No scalar -> fall back to the first row's amount column.
        result = BudgetSummaryBuilder().build(
            spec=_spec("budget_summary", budget=200),
            data=DataSet(rows=({"amount": 50},)),
        )
        assert result["actual"] == 50.0
        assert result["variance"] == -150.0
        assert result["utilization"] == 0.25

    def test_budget_summary_zero_budget_yields_none_utilization(self) -> None:
        # No scalar, no rows, and a non-numeric budget collapse to zeros;
        # a zero budget makes utilization undefined (None), not a ZeroDiv.
        result = BudgetSummaryBuilder().build(
            spec=_spec("budget_summary", budget="not-a-number"),
            data=DataSet(),
        )
        assert result["budget"] == 0.0
        assert result["actual"] == 0.0
        assert result["utilization"] is None

    def test_cost_summary_rejects_non_finite_and_bool_amounts(self) -> None:
        # bool is not a number here; 'nan'/'inf' strings parse via float()
        # but are dropped so they cannot poison the total or the JSON body.
        data = DataSet(
            rows=(
                {"group": "ok", "amount": 10},
                {"group": "flag", "amount": True},
                {"group": "nan", "amount": "nan"},
                {"group": "inf", "amount": "inf"},
                {"group": "text", "amount": "oops"},
            )
        )
        result = CostSummaryBuilder().build(spec=_spec("cost_summary"), data=data)
        # Only the single finite numeric amount contributes to the total.
        assert result["total"] == 10.0
        # Non-numeric amounts pass through as None rather than crashing.
        amounts = [r["amount"] for r in result["rows"]]
        assert amounts == [10, None, None, None, None]
        assert result["currency"] == "USD"


class TestCompositeExpansion:
    def test_split_graph_from_series(self) -> None:
        data = DataSet(
            series=(
                Series(label="a", points=((1.0, 2.0), (3.0, 4.0))),
                Series(label="b", points=((1.0, 5.0),)),
            )
        )
        result = SplitGraphBuilder().build(spec=_spec("split_graph"), data=data)
        assert [p["label"] for p in result["panels"]] == ["a", "b"]

    def test_iframe_https_only(self) -> None:
        # https + real host: accepted.
        good = IframeBuilder().build(
            spec=_spec("iframe", src="https://example.com/x", height=400),
            data=DataSet(),
        )
        assert good["src"] == "https://example.com/x"
        assert good["height"] == 400
        # http: rejected.
        bad = IframeBuilder().build(
            spec=_spec("iframe", src="http://plain.example/x"),
            data=DataSet(),
        )
        assert bad["src"] is None


class TestDefaultRegistryGrew:
    def test_expected_types_present(self) -> None:
        names = {b.type_name for b in default_widget_builders()}
        # Spot-check a set that covers every new family so a future
        # regression that drops one is caught.
        must_have = {
            "pie_chart",
            "scatter_plot",
            "sparkline",
            "gauge",
            "progress_bar",
            "event_stream",
            "retention",
            "alert_status",
            "check_status",
            "service_summary",
            "flame_graph",
            "hostmap",
            "topology_map",
            "geomap",
            "cost_summary",
            "budget_summary",
            "split_graph",
            "iframe",
            "process_steps",
            "comparison",
        }
        assert must_have <= names
