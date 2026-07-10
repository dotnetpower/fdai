"""Tests for the batch-8 expansion: new formats + new API endpoints + cache."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from fdai.core.reporting.cache import InMemoryReportCache
from fdai.core.reporting.datasources import (
    AuditDataSource,
    NoopDataSource,
    StaticDataSource,
)
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.formats import (
    HtmlFormatEncoder,
    NdjsonFormatEncoder,
    PrometheusFormatEncoder,
    TextFormatEncoder,
    install_default_formats,
)
from fdai.core.reporting.models import (
    DataSet,
    QuerySpec,
    RenderedReport,
    RenderedWidget,
    ReportSpec,
    TimeRange,
    Variable,
    WidgetSpec,
)
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    FormatRegistry,
    ReportCatalog,
    WidgetRegistry,
)
from fdai.core.reporting.widgets import install_default_widgets
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.reporting import ReportingConfig

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _rendered_report_with(widgets: tuple[RenderedWidget, ...]) -> RenderedReport:
    return RenderedReport(
        id="r",
        version="1.0.0",
        name="R",
        description="",
        generated_at=_NOW,
        time_range=(_NOW - timedelta(hours=1), _NOW),
        variables={},
        widgets=widgets,
    )


class TestHtmlEncoder:
    def test_scalar_and_table_html(self) -> None:
        report = _rendered_report_with(
            (
                RenderedWidget(
                    id="v",
                    type="query_value",
                    title="Value",
                    data={"value": "<b>7</b>"},
                ),
                RenderedWidget(
                    id="t",
                    type="table",
                    title="T",
                    data={"columns": ["a"], "rows": [{"a": "<script>"}]},
                ),
            )
        )
        body = HtmlFormatEncoder().encode(report).decode("utf-8")
        # `<article>` wrapper + escaped cells.
        assert body.startswith("<article")
        assert "&lt;script&gt;" in body
        # Values also escaped so raw HTML in a cell never renders.
        assert "&lt;b&gt;7&lt;/b&gt;" in body


class TestTextEncoder:
    def test_stdout_summary(self) -> None:
        report = _rendered_report_with(
            (RenderedWidget(id="v", type="query_value", title="Value", data={"value": 42}),)
        )
        body = TextFormatEncoder().encode(report).decode("utf-8")
        assert "# R" in body
        assert "value: 42" in body


class TestNdjsonEncoder:
    def test_one_object_per_line(self) -> None:
        report = _rendered_report_with(
            (
                RenderedWidget(id="v", type="query_value", title="Value", data={"value": 7}),
                RenderedWidget(
                    id="s",
                    type="timeseries",
                    title="S",
                    data={"series": [{"label": "a", "labels": {}, "points": [[1.0, 2.0]]}]},
                ),
            )
        )
        body = NdjsonFormatEncoder().encode(report).decode("utf-8")
        lines = [line for line in body.splitlines() if line]
        assert len(lines) == 3  # header + 2 widgets
        assert json.loads(lines[0])["kind"] == "report"
        assert json.loads(lines[1])["id"] == "v"


class TestPrometheusEncoder:
    def test_query_value_and_timeseries_emitted(self) -> None:
        report = _rendered_report_with(
            (
                RenderedWidget(id="v", type="query_value", title="Val", data={"value": 42}),
                RenderedWidget(
                    id="ts",
                    type="timeseries",
                    title="Trend",
                    data={"series": [{"label": "a", "labels": {}, "points": [[1.0, 100.0]]}]},
                ),
                RenderedWidget(
                    id="skip", type="table", title="Skip", data={"columns": [], "rows": []}
                ),
            )
        )
        body = PrometheusFormatEncoder().encode(report).decode("utf-8")
        # Scalar and series both emit; table is silently skipped.
        assert "fdai_report_r_v 42" in body
        assert 'fdai_report_r_ts{series="a"} 100.0' in body
        assert "fdai_report_r_skip" not in body


# ---- API endpoints ---------------------------------------------------


def _engine_with_static() -> ReportEngine:
    reader = InMemoryConsoleReadModel()
    reader.record_audit_entry(
        {"event_id": "00000000-0000-0000-0000-000000000000"},
        actor="thor",
        action_kind="k",
        mode="shadow",
    )
    widgets = install_default_widgets(WidgetRegistry())
    sources = DataSourceRegistry(
        (
            AuditDataSource(reader=reader),
            StaticDataSource(name="static_s", dataset=DataSet(scalar=1)),
            NoopDataSource(name="report_feed"),
            NoopDataSource(name="metric"),
            NoopDataSource(name="log_query"),
        )
    )
    return ReportEngine(catalog=ReportCatalog(), sources=sources, widgets=widgets)


def _client(engine: ReportEngine) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    os.environ["FDAI_READ_API_DEV_MODE"] = "1"
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            reporting=ReportingConfig(
                engine=engine,
                formats=install_default_formats(FormatRegistry()),
            ),
        ),
    )
    return TestClient(app)


class TestNewApiEndpoints:
    def test_formats_endpoint_lists_encoders(self) -> None:
        client = _client(_engine_with_static())
        try:
            response = client.get("/reports/formats")
            assert response.status_code == 200
            names = {item["name"] for item in response.json()["items"]}
            assert {"json", "markdown", "csv", "html", "text", "ndjson"} <= names
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)

    def test_widget_types_endpoint(self) -> None:
        client = _client(_engine_with_static())
        try:
            response = client.get("/reports/widget-types")
            assert response.status_code == 200
            names = set(response.json()["items"])
            assert {"timeseries", "table", "pie_chart"} <= names
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)

    def test_datasources_endpoint(self) -> None:
        client = _client(_engine_with_static())
        try:
            response = client.get("/reports/datasources")
            assert response.status_code == 200
            names = set(response.json()["items"])
            assert {"audit", "static_s"} <= names
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)

    def test_health_endpoint(self) -> None:
        client = _client(_engine_with_static())
        try:
            response = client.get("/reports/health")
            assert response.status_code == 200
            payload = response.json()
            assert "reports" in payload
            assert "config" in payload
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)


# ---- InMemoryReportCache --------------------------------------------


class _CountingSource:
    name = "count"

    def __init__(self) -> None:
        self.calls = 0

    async def query(self, spec, *, since, until, variables):
        self.calls += 1
        return DataSet(scalar=self.calls)


def _cache_engine() -> tuple[ReportEngine, _CountingSource]:
    source = _CountingSource()
    widgets = install_default_widgets(WidgetRegistry())
    sources = DataSourceRegistry((source,))
    report = ReportSpec(
        id="r",
        version="1.0.0",
        name="R",
        description="",
        time_range=TimeRange(relative_duration=timedelta(hours=1)),
        variables=(Variable(name="env", default="prod"),),
        widgets=(
            WidgetSpec(
                id="v",
                type="query_value",
                title="v",
                query=QuerySpec(datasource="count"),
            ),
        ),
    )
    engine = ReportEngine(
        catalog=ReportCatalog((report,)),
        sources=sources,
        widgets=widgets,
    )
    return engine, source


class TestInMemoryReportCache:
    async def test_repeat_render_hits_cache(self) -> None:
        engine, source = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=60, max_entries=10)
        first = await cache.render("r")
        second = await cache.render("r")
        # Same rendered payload came back (identity check on the dataclass).
        assert first is second
        assert source.calls == 1

    async def test_different_variables_are_different_keys(self) -> None:
        engine, source = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=60, max_entries=10)
        await cache.render("r", variables={"env": "prod"})
        await cache.render("r", variables={"env": "prod"})
        await cache.render("r", variables={"env": "staging"})
        # First key hits cache once, second key misses once -> 2 calls.
        assert source.calls == 2

    async def test_invalidate_clears_cache(self) -> None:
        engine, source = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=60, max_entries=10)
        await cache.render("r")
        cache.invalidate("r")
        await cache.render("r")
        assert source.calls == 2

    async def test_invalidate_all_clears_every_report(self) -> None:
        engine, source = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=60, max_entries=10)
        await cache.render("r", variables={"env": "a"})
        await cache.render("r", variables={"env": "b"})
        # No report_id -> the whole cache is dropped in one call.
        cache.invalidate()
        assert cache.health()["cache"]["size"] == 0
        await cache.render("r", variables={"env": "a"})
        assert source.calls == 3

    async def test_ttl_expiry_re_renders(self) -> None:
        engine, source = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=0.05, max_entries=10)
        await cache.render("r")
        await asyncio.sleep(0.06)
        await cache.render("r")
        assert source.calls == 2

    def test_health_carries_cache_stats(self) -> None:
        engine, _ = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=30, max_entries=5)
        payload = cache.health()
        assert payload["cache"]["max_entries"] == 5

    def test_validation(self) -> None:
        engine, _ = _cache_engine()
        with pytest.raises(ValueError):
            InMemoryReportCache(engine, ttl_seconds=0)
        with pytest.raises(ValueError):
            InMemoryReportCache(engine, max_entries=0)

    def test_facade_methods_forward_to_wrapped_engine(self) -> None:
        engine, _ = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=30, max_entries=5)
        # The cache is a transparent facade: each accessor returns the
        # wrapped engine's own object so callers never know it is cached.
        assert cache.catalog() is engine.catalog()
        assert cache.widget_registry() is engine.widget_registry()
        assert cache.datasource_registry() is engine.datasource_registry()
        assert cache.config() is engine.config()

    async def test_lru_eviction_drops_oldest_entry(self) -> None:
        engine, source = _cache_engine()
        cache = InMemoryReportCache(engine, ttl_seconds=60, max_entries=2)
        # Three distinct variable keys against a 2-entry cache -> the
        # oldest (env=a) is evicted once env=c is written.
        await cache.render("r", variables={"env": "a"})
        await cache.render("r", variables={"env": "b"})
        await cache.render("r", variables={"env": "c"})
        assert cache.health()["cache"]["size"] == 2
        assert source.calls == 3
        # env=a was evicted, so rendering it again is a miss (re-render).
        await cache.render("r", variables={"env": "a"})
        assert source.calls == 4
        # env=c is still hot, so it hits the cache (no new render).
        await cache.render("r", variables={"env": "c"})
        assert source.calls == 4

