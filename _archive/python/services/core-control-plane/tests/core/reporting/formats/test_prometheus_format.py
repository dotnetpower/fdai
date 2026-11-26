"""Coverage for Prometheus report encoding."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.reporting.formats.prometheus_format import PrometheusFormatEncoder
from fdai.core.reporting.models import RenderedReport, RenderedWidget


def _report(*widgets: RenderedWidget) -> RenderedReport:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    return RenderedReport(
        id="sre.report",
        version="1.0.0",
        name="SRE",
        description="Example",
        generated_at=now,
        time_range=(now, now),
        variables={},
        widgets=widgets,
    )


def test_encoder_handles_scalar_series_nested_and_invalid_widgets() -> None:
    scalar = RenderedWidget(
        id="success-rate",
        type="query_value",
        title="Success\nrate",
        data={"value": "99.5"},
    )
    series = RenderedWidget(
        id="latency",
        type="timeseries",
        title='Latency \\"p95"',
        data={
            "series": (
                {"label": 'api\\"one', "points": (("t1", "3.5"),)},
                {"label": "empty", "points": ()},
                {"label": "values", "values": ("1", "4")},
                {"label": "bad-points", "points": (("t1", object()),)},
                {"label": "bad-values", "values": (object(),)},
                "invalid",
            )
        },
    )
    nested = RenderedWidget(
        id="group",
        type="group",
        title="Group",
        data={},
        children=(
            RenderedWidget(
                id="count",
                type="query_value",
                title="",
                data={"value": 2},
            ),
        ),
    )
    ignored = RenderedWidget(
        id="ignored",
        type="query_value",
        title="Ignored",
        data={"value": True},
        error="unavailable",
    )
    invalid_scalars = (
        RenderedWidget(
            id="bool",
            type="query_value",
            title="Boolean",
            data={"value": True},
        ),
        RenderedWidget(
            id="object",
            type="query_value",
            title="Object",
            data={"value": object()},
        ),
    )

    output = (
        PrometheusFormatEncoder()
        .encode(_report(scalar, series, nested, ignored, *invalid_scalars))
        .decode()
    )

    assert "fdai_report_sre_report_success_rate 99.5" in output
    assert 'series="api\\\\\\"one"} 3.5' in output
    assert 'series="values"} 4.0' in output
    assert "fdai_report_sre_report_count 2.0" in output
    assert "Success rate" in output
    assert "ignored" not in output
