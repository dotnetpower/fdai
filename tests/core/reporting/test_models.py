"""Model-level tests: TimeRange resolution + RenderedReport.to_dict shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.reporting.models import (
    RenderedReport,
    RenderedWidget,
    Series,
    TimeRange,
)


class TestTimeRange:
    def test_absolute_window_wins_over_now(self) -> None:
        since = datetime(2026, 1, 1, tzinfo=UTC)
        until = datetime(2026, 1, 2, tzinfo=UTC)
        rng = TimeRange(since=since, until=until)
        assert rng.resolve(now=datetime(2030, 5, 5, tzinfo=UTC)) == (since, until)

    def test_relative_duration_uses_now_as_until(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        rng = TimeRange(relative_duration=timedelta(hours=6))
        since, until = rng.resolve(now=now)
        assert until == now
        assert since == now - timedelta(hours=6)

    def test_since_only_uses_now_as_until(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        since = datetime(2026, 7, 9, tzinfo=UTC)
        rng = TimeRange(since=since)
        assert rng.resolve(now=now) == (since, now)

    def test_empty_range_raises(self) -> None:
        with pytest.raises(ValueError, match="since / relative_duration"):
            TimeRange().resolve(now=datetime(2026, 1, 1, tzinfo=UTC))


class TestRenderedReport:
    def test_to_dict_shape_matches_fe_contract(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = RenderedReport(
            id="demo",
            version="1.0.0",
            name="Demo",
            description="d",
            generated_at=now,
            time_range=(now - timedelta(hours=1), now),
            variables={"env": "prod"},
            widgets=(
                RenderedWidget(
                    id="v",
                    type="query_value",
                    title="Val",
                    data={"value": 42},
                ),
                RenderedWidget(
                    id="ts",
                    type="timeseries",
                    title="Trend",
                    data={"series": [{"label": "a", "labels": {}, "points": [[1.0, 2.0]]}]},
                ),
            ),
            tags=("ops",),
        )
        payload = report.to_dict()
        assert payload["id"] == "demo"
        assert payload["version"] == "1.0.0"
        assert payload["variables"] == {"env": "prod"}
        assert payload["time_range"] == {
            "since": (now - timedelta(hours=1)).isoformat(),
            "until": now.isoformat(),
        }
        assert [w["id"] for w in payload["widgets"]] == ["v", "ts"]
        # Ensure defensive copies - mutating the returned dict never
        # leaks into another call (frozen dataclass promise).
        payload["widgets"][0]["data"]["value"] = 99
        second = report.to_dict()
        assert second["widgets"][0]["data"]["value"] == 42

    def test_error_widget_serialized_when_present(self) -> None:
        report = RenderedReport(
            id="demo",
            version="1.0.0",
            name="Demo",
            description="d",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            time_range=(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 1, 1, tzinfo=UTC),
            ),
            variables={},
            widgets=(
                RenderedWidget(
                    id="broken",
                    type="table",
                    title="t",
                    data={},
                    error="datasource error: RuntimeError: boom",
                ),
            ),
        )
        payload = report.to_dict()
        assert payload["widgets"][0]["error"] == "datasource error: RuntimeError: boom"


class TestSeriesShape:
    def test_series_default_empty_points(self) -> None:
        s = Series(label="a")
        assert s.points == ()
        assert s.labels == {}
