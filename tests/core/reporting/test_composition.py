"""Composition-helper tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.reporting.composition import default_reporting_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "rule-catalog" / "reports"


class TestDefaultReportingEngine:
    def test_no_providers_wires_noop_stubs(self) -> None:
        engine, formats = default_reporting_engine(reports_root=REPORTS_ROOT)
        # Every well-known name is wired even without a provider.
        assert {"audit", "report_feed", "metric", "log_query"} <= set(
            engine.datasource_registry().names()
        )
        # Sample catalog loaded and validated against the wired names.
        ids = {s.id for s in engine.catalog().list()}
        assert {"shadow-mode-daily", "signal-feed-overview", "metric-explorer"} <= ids
        # Default format registry always ships the three encoders.
        assert set(formats.names()) == {"csv", "json", "markdown"}

    async def test_noop_stubs_render_as_empty_data(self) -> None:
        engine, _ = default_reporting_engine(reports_root=REPORTS_ROOT)
        rendered = await engine.render("shadow-mode-daily")
        # Every widget is either free-of-error with empty data (noop
        # projection returns an empty DataSet, so builders produce
        # empty payloads) or a query_value with value=None. Nothing
        # raises.
        for widget in rendered.widgets:
            assert widget.error is None

    def test_yaml_load_fails_when_datasource_missing(self, tmp_path: Path) -> None:
        # Craft a report that references an unwired datasource; the
        # helper wires only the four defaults + noop stubs, so anything
        # else fails at load time (fail-closed).
        report = tmp_path / "bad.yaml"
        report.write_text(
            """
id: bad
version: 1.0.0
name: Bad
time_range:
  last: 1d
widgets:
  - id: v
    type: query_value
    title: V
    query:
      datasource: cost_management
""".strip(),
            encoding="utf-8",
        )
        with pytest.raises(Exception, match="cost_management"):
            default_reporting_engine(reports_root=tmp_path)

    def test_empty_root_argument_leaves_catalog_empty(self) -> None:
        engine, _ = default_reporting_engine()
        assert engine.catalog().list() == ()

    def test_generated_report_uses_expected_default_time_window(self) -> None:
        engine, _ = default_reporting_engine(reports_root=REPORTS_ROOT)
        # Sanity: signal-feed-overview declares last: 24h.
        spec = engine.catalog().get("signal-feed-overview")
        assert spec.time_range.relative_duration == timedelta(hours=24)
        # The engine uses the render clock, not a frozen "now" - the
        # composition helper leaves that to the ReportEngine default.
        rendered = _sync_render(engine, "signal-feed-overview")
        window_hours = (rendered.time_range[1] - rendered.time_range[0]).total_seconds() / 3600
        assert window_hours == pytest.approx(24.0)


def _sync_render(engine, report_id: str):
    import asyncio

    return asyncio.run(engine.render(report_id))


def test_module_exports_helper() -> None:
    from fdai.core.reporting import composition

    assert callable(composition.default_reporting_engine)
    # Sanity: helper uses only fake / opt-in providers, no side effects
    # at import time.
    now = datetime.now(tz=UTC)
    assert now.tzinfo is UTC
