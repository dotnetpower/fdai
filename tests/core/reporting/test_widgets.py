"""Widget-builder unit tests: every default builder emits the contract shape."""

from __future__ import annotations

from typing import Any

import pytest

from fdai.core.reporting.models import DataSet, Series, WidgetSpec
from fdai.core.reporting.widgets import (
    BarChartBuilder,
    ChangeBuilder,
    DistributionBuilder,
    FreeTextBuilder,
    FunnelBuilder,
    HeatmapBuilder,
    ImageBuilder,
    ListStreamBuilder,
    NoteBuilder,
    QueryValueBuilder,
    SankeyBuilder,
    SloSummaryBuilder,
    TableBuilder,
    TimeseriesBuilder,
    TopListBuilder,
    TreemapBuilder,
    default_widget_builders,
)


def _spec(widget_type: str, **options: Any) -> WidgetSpec:
    return WidgetSpec(id="w", type=widget_type, title="t", options=options)


class TestTimeseriesBuilder:
    def test_series_shape(self) -> None:
        data = DataSet(
            series=(
                Series(
                    label="a",
                    points=((1.0, 10.0), (2.0, 20.0)),
                    labels={"env": "prod"},
                ),
            )
        )
        result = TimeseriesBuilder().build(spec=_spec("timeseries"), data=data)
        assert result == {
            "series": [
                {
                    "label": "a",
                    "labels": {"env": "prod"},
                    "points": [[1.0, 10.0], [2.0, 20.0]],
                }
            ]
        }


class TestQueryValueBuilder:
    def test_scalar_wins(self) -> None:
        result = QueryValueBuilder().build(
            spec=_spec("query_value", unit="ms", precision=2),
            data=DataSet(scalar=42),
        )
        assert result == {"value": 42, "unit": "ms", "precision": 2}

    def test_falls_back_to_first_row_first_column(self) -> None:
        result = QueryValueBuilder().build(
            spec=_spec("query_value"),
            data=DataSet(columns=("val",), rows=({"val": 7},)),
        )
        assert result == {"value": 7}

    def test_none_when_no_data(self) -> None:
        result = QueryValueBuilder().build(spec=_spec("query_value"), data=DataSet())
        assert result == {"value": None}


class TestChangeBuilder:
    def test_delta_from_two_rows(self) -> None:
        data = DataSet(rows=({"value": 100}, {"value": 150}))
        result = ChangeBuilder().build(spec=_spec("change"), data=data)
        assert result == {
            "current": 150,
            "previous": 100,
            "delta_absolute": 50,
            "delta_ratio": 0.5,
        }

    def test_delta_from_series(self) -> None:
        data = DataSet(series=(Series(label="a", points=((1.0, 200.0), (2.0, 100.0))),))
        result = ChangeBuilder().build(spec=_spec("change"), data=data)
        assert result["current"] == 100.0
        assert result["previous"] == 200.0
        assert result["delta_absolute"] == -100.0

    def test_ratio_none_when_previous_zero(self) -> None:
        data = DataSet(rows=({"value": 0}, {"value": 42}))
        result = ChangeBuilder().build(spec=_spec("change"), data=data)
        assert result["delta_ratio"] is None

    def test_missing_data_yields_none_payload(self) -> None:
        result = ChangeBuilder().build(spec=_spec("change"), data=DataSet())
        assert result == {
            "current": None,
            "previous": None,
            "delta_absolute": None,
            "delta_ratio": None,
        }


class TestDistributionBuilder:
    def test_buckets_sorted_ascending(self) -> None:
        data = DataSet(
            rows=(
                {"bucket": 100, "count": 5},
                {"bucket": 10, "count": 2},
                {"bucket": 50, "count": 3},
            )
        )
        result = DistributionBuilder().build(spec=_spec("distribution"), data=data)
        assert result["buckets"] == [
            {"le": 10, "count": 2},
            {"le": 50, "count": 3},
            {"le": 100, "count": 5},
        ]

    def test_custom_field_names(self) -> None:
        data = DataSet(rows=({"upper": 1, "n": 9},))
        result = DistributionBuilder().build(
            spec=_spec("distribution", bucket_field="upper", count_field="n"),
            data=data,
        )
        assert result["buckets"] == [{"le": 1, "count": 9}]


class TestHeatmapBuilder:
    def test_reuses_series_shape(self) -> None:
        data = DataSet(series=(Series(label="a", points=((1.0, 2.0),)),))
        result = HeatmapBuilder().build(spec=_spec("heatmap"), data=data)
        assert result == {
            "series": [{"label": "a", "labels": {}, "points": [[1.0, 2.0]]}]
        }


class TestBarChartBuilder:
    def test_default_fields(self) -> None:
        data = DataSet(rows=({"label": "a", "value": 1}, {"label": "b", "value": 2}))
        result = BarChartBuilder().build(spec=_spec("bar_chart"), data=data)
        assert result == {"bars": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]}


class TestTableBuilder:
    def test_column_projection_and_row_limit(self) -> None:
        data = DataSet(
            columns=("a", "b"),
            rows=({"a": 1, "b": 2, "c": 99}, {"a": 3, "b": 4}, {"a": 5, "b": 6}),
        )
        result = TableBuilder().build(spec=_spec("table", limit=2), data=data)
        assert result["columns"] == ["a", "b"]
        assert result["rows"] == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        assert result["total_rows"] == 3

    def test_columns_derived_from_first_row_when_absent(self) -> None:
        data = DataSet(rows=({"x": 1, "y": 2},))
        result = TableBuilder().build(spec=_spec("table"), data=data)
        assert set(result["columns"]) == {"x", "y"}


class TestTopListBuilder:
    def test_desc_by_value(self) -> None:
        data = DataSet(
            columns=("label", "value"),
            rows=(
                {"label": "a", "value": 5},
                {"label": "b", "value": 20},
                {"label": "c", "value": 10},
            ),
        )
        result = TopListBuilder().build(spec=_spec("top_list", limit=2), data=data)
        assert [row["label"] for row in result["rows"]] == ["b", "c"]
        assert result["ranked_by"] == "value"
        assert result["order"] == "desc"

    def test_asc_and_custom_rank(self) -> None:
        data = DataSet(
            rows=(
                {"name": "a", "count": 5},
                {"name": "b", "count": 20},
                {"name": "c", "count": 10},
            )
        )
        result = TopListBuilder().build(
            spec=_spec("top_list", rank_by="count", order="asc", limit=2),
            data=data,
        )
        assert [row["name"] for row in result["rows"]] == ["a", "c"]

    def test_rows_missing_rank_column_dropped(self) -> None:
        data = DataSet(rows=({"a": 1}, {"a": 2, "value": 9},))
        result = TopListBuilder().build(spec=_spec("top_list"), data=data)
        assert len(result["rows"]) == 1


class TestListStreamBuilder:
    def test_newest_first_by_default_timestamp(self) -> None:
        data = DataSet(
            rows=(
                {"at": "2026-01-01T00:00:00Z", "msg": "old"},
                {"at": "2026-06-01T00:00:00Z", "msg": "new"},
            )
        )
        result = ListStreamBuilder().build(spec=_spec("list_stream"), data=data)
        assert [row["msg"] for row in result["items"]] == ["new", "old"]

    def test_limit_bounded(self) -> None:
        data = DataSet(rows=tuple({"at": str(i)} for i in range(120)))
        result = ListStreamBuilder().build(spec=_spec("list_stream", limit=5), data=data)
        assert len(result["items"]) == 5


class TestFunnelBuilder:
    def test_conversion_ratios(self) -> None:
        data = DataSet(
            rows=(
                {"stage": "visits", "value": 1000},
                {"stage": "signups", "value": 250},
                {"stage": "purchase", "value": 25},
            )
        )
        result = FunnelBuilder().build(spec=_spec("funnel"), data=data)
        ratios = [s["conversion_ratio"] for s in result["stages"]]
        assert ratios == [1.0, 0.25, 0.025]


class TestSankeyBuilder:
    def test_nodes_and_summed_links(self) -> None:
        data = DataSet(
            rows=(
                {"source": "a", "target": "b", "value": 1},
                {"source": "a", "target": "b", "value": 2},
                {"source": "b", "target": "c", "value": 4},
            )
        )
        result = SankeyBuilder().build(spec=_spec("sankey"), data=data)
        assert {n["id"] for n in result["nodes"]} == {"a", "b", "c"}
        by_pair: dict[tuple[str, str], float] = {
            (link["source"], link["target"]): link["value"] for link in result["links"]
        }
        assert by_pair[("a", "b")] == 3.0
        assert by_pair[("b", "c")] == 4.0


class TestTreemapBuilder:
    def test_sorted_desc_by_value(self) -> None:
        data = DataSet(rows=({"label": "a", "value": 1}, {"label": "b", "value": 5}))
        result = TreemapBuilder().build(spec=_spec("treemap"), data=data)
        assert [t["label"] for t in result["tiles"]] == ["b", "a"]

    def test_group_field_carried_when_configured(self) -> None:
        data = DataSet(rows=({"label": "a", "value": 1, "team": "ops"},))
        result = TreemapBuilder().build(
            spec=_spec("treemap", group_field="team"),
            data=data,
        )
        assert result["tiles"][0]["group"] == "ops"


class TestSloSummaryBuilder:
    def test_row_extracted(self) -> None:
        data = DataSet(
            rows=(
                {
                    "objective": "availability",
                    "attainment": 0.995,
                    "target": 0.99,
                    "error_budget": 0.01,
                    "error_budget_remaining": 0.005,
                    "burn_rate": 0.5,
                    "window": "30d",
                },
            )
        )
        result = SloSummaryBuilder().build(spec=_spec("slo_summary"), data=data)
        assert result["objective"] == "availability"
        assert result["measured"] is True

    def test_measured_false_when_no_rows(self) -> None:
        result = SloSummaryBuilder().build(spec=_spec("slo_summary"), data=DataSet())
        assert result["measured"] is False
        assert result["attainment"] is None


class TestAnnotations:
    def test_free_text_returns_body(self) -> None:
        result = FreeTextBuilder().build(
            spec=_spec("free_text", body="hello"),
            data=DataSet(),
        )
        assert result == {"body": "hello"}

    def test_note_severity_validated(self) -> None:
        result = NoteBuilder().build(
            spec=_spec("note", body="x", severity="bogus"),
            data=DataSet(),
        )
        assert result["severity"] == "info"

    def test_image_https_allowed(self) -> None:
        result = ImageBuilder().build(
            spec=_spec("image", src="https://example.com/a.png", alt="a"),
            data=DataSet(),
        )
        assert result["src"] == "https://example.com/a.png"

    @pytest.mark.parametrize(
        "bad_src",
        ("javascript:alert(1)", "http://plain-http.example/a.png", "data:image/png;base64,xx"),
    )
    def test_image_rejects_bad_schemes(self, bad_src: str) -> None:
        result = ImageBuilder().build(
            spec=_spec("image", src=bad_src, alt="a"),
            data=DataSet(),
        )
        assert result["src"] is None
        assert result["error"] == "unsupported url scheme"


class TestDefaults:
    def test_defaults_are_registered_by_type_name(self) -> None:
        # Every default builder MUST expose a unique `type_name`; the
        # engine keys on that name.
        types = [b.type_name for b in default_widget_builders()]
        assert len(types) == len(set(types))
        assert "timeseries" in types
        assert "query_value" in types
        assert "sankey" in types
        assert "group" not in types  # engine-special-cased
