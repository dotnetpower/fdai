"""End-to-end engine tests using in-memory fakes.

Covers: variable resolution, unknown datasource error isolation,
builder error isolation, group widget recursion, deterministic clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.core.reporting.contracts import (
    ReportDataSource,
    ReportNotFoundError,
    VariableRejectedError,
)
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.models import (
    DataSet,
    QuerySpec,
    ReportSpec,
    TimeRange,
    Variable,
    WidgetSpec,
)
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    ReportCatalog,
    WidgetRegistry,
)
from fdai.core.reporting.widgets import install_default_widgets


class FakeDataSource:
    """Yield a canned :class:`DataSet` and record every call."""

    def __init__(self, name: str, dataset: DataSet) -> None:
        self._name = name
        self._dataset = dataset
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    async def query(
        self,
        spec: QuerySpec,
        *,
        since: datetime,
        until: datetime,
        variables: Mapping[str, str],
    ) -> DataSet:
        self.calls.append(
            {
                "spec": spec,
                "since": since,
                "until": until,
                "variables": dict(variables),
            }
        )
        return self._dataset


class FailingDataSource:
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def query(self, spec: QuerySpec, **_: Any) -> DataSet:
        raise RuntimeError("bang")


def _fixed_clock(now: datetime):
    def _clock() -> datetime:
        return now

    return _clock


def _build_engine(
    *,
    sources: tuple[ReportDataSource, ...] = (),
    reports: tuple[ReportSpec, ...] = (),
    now: datetime | None = None,
) -> ReportEngine:
    widgets = install_default_widgets(WidgetRegistry())
    return ReportEngine(
        catalog=ReportCatalog(reports),
        sources=DataSourceRegistry(sources),
        widgets=widgets,
        clock=_fixed_clock(now or datetime(2026, 7, 10, 12, 0, tzinfo=UTC)),
    )


class TestEngineRender:
    async def test_renders_declared_widgets_in_order(self) -> None:
        source = FakeDataSource(
            name="kpi",
            dataset=DataSet(scalar=42),
        )
        report = ReportSpec(
            id="ops",
            version="1.0.0",
            name="Ops",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            widgets=(
                WidgetSpec(
                    id="v",
                    type="query_value",
                    title="Val",
                    query=QuerySpec(datasource="kpi"),
                ),
            ),
        )
        engine = _build_engine(sources=(source,), reports=(report,))
        rendered = await engine.render("ops")

        assert rendered.id == "ops"
        assert rendered.widgets[0].type == "query_value"
        assert rendered.widgets[0].data == {"value": 42}
        assert rendered.widgets[0].error is None
        assert len(source.calls) == 1

    async def test_group_widget_recurses_without_datasource(self) -> None:
        text_report = ReportSpec(
            id="text-only",
            version="1.0.0",
            name="Text",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            widgets=(
                WidgetSpec(
                    id="section-a",
                    type="group",
                    title="Section A",
                    children=(
                        WidgetSpec(
                            id="intro",
                            type="free_text",
                            title="Intro",
                            options={"body": "hi"},
                        ),
                    ),
                ),
            ),
        )
        engine = _build_engine(reports=(text_report,))
        rendered = await engine.render("text-only")
        assert rendered.widgets[0].type == "group"
        assert rendered.widgets[0].children[0].data == {"body": "hi"}

    async def test_unknown_datasource_becomes_error_widget(self) -> None:
        report = ReportSpec(
            id="broken",
            version="1.0.0",
            name="Broken",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            widgets=(
                WidgetSpec(
                    id="v",
                    type="query_value",
                    title="Val",
                    query=QuerySpec(datasource="does-not-exist"),
                ),
            ),
        )
        engine = _build_engine(reports=(report,))
        rendered = await engine.render("broken")
        widget = rendered.widgets[0]
        assert widget.data == {}
        assert widget.error is not None
        assert "unknown datasource" in widget.error

    async def test_datasource_failure_isolated_to_widget(self) -> None:
        good_source = FakeDataSource(name="ok", dataset=DataSet(scalar=7))
        bad_source = FailingDataSource(name="bad")
        report = ReportSpec(
            id="mixed",
            version="1.0.0",
            name="Mixed",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            widgets=(
                WidgetSpec(
                    id="good",
                    type="query_value",
                    title="Good",
                    query=QuerySpec(datasource="ok"),
                ),
                WidgetSpec(
                    id="bad",
                    type="query_value",
                    title="Bad",
                    query=QuerySpec(datasource="bad"),
                ),
            ),
        )
        engine = _build_engine(sources=(good_source, bad_source), reports=(report,))
        rendered = await engine.render("mixed")

        assert rendered.widgets[0].data == {"value": 7}
        assert rendered.widgets[0].error is None
        assert rendered.widgets[1].error is not None
        assert "bang" in rendered.widgets[1].error

    async def test_missing_report_raises(self) -> None:
        engine = _build_engine()
        with pytest.raises(ReportNotFoundError):
            await engine.render("nope")

    async def test_time_range_forwarded_to_source(self) -> None:
        source = FakeDataSource(name="kpi", dataset=DataSet(scalar=0))
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = ReportSpec(
            id="ops",
            version="1.0.0",
            name="Ops",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=2)),
            widgets=(
                WidgetSpec(
                    id="v",
                    type="query_value",
                    title="Val",
                    query=QuerySpec(datasource="kpi"),
                ),
            ),
        )
        engine = _build_engine(sources=(source,), reports=(report,), now=now)
        await engine.render("ops")
        call = source.calls[0]
        assert call["until"] == now
        assert call["since"] == now - timedelta(hours=2)


class TestVariableResolution:
    async def test_defaults_and_overrides_applied(self) -> None:
        source = FakeDataSource(name="kpi", dataset=DataSet(scalar=1))
        report = ReportSpec(
            id="v",
            version="1.0.0",
            name="V",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            variables=(
                Variable(name="env", default="prod", values=("prod", "staging")),
                Variable(name="region", default="koreacentral"),
            ),
            widgets=(
                WidgetSpec(
                    id="v",
                    type="query_value",
                    title="V",
                    query=QuerySpec(datasource="kpi"),
                ),
            ),
        )
        engine = _build_engine(sources=(source,), reports=(report,))
        rendered = await engine.render("v", variables={"env": "staging"})
        assert rendered.variables == {"env": "staging", "region": "koreacentral"}
        # Datasource sees the resolved (not raw) map.
        assert source.calls[0]["variables"] == {"env": "staging", "region": "koreacentral"}

    async def test_override_outside_allowlist_rejected(self) -> None:
        report = ReportSpec(
            id="v",
            version="1.0.0",
            name="V",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            variables=(Variable(name="env", default="prod", values=("prod",)),),
        )
        engine = _build_engine(reports=(report,))
        with pytest.raises(VariableRejectedError, match="allowlist"):
            await engine.render("v", variables={"env": "dev"})

    async def test_unknown_override_rejected(self) -> None:
        report = ReportSpec(
            id="v",
            version="1.0.0",
            name="V",
            description="d",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
        )
        engine = _build_engine(reports=(report,))
        with pytest.raises(VariableRejectedError, match="unknown variable"):
            await engine.render("v", variables={"typo": "x"})
