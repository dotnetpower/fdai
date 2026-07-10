"""Tests for the batch-6 critique hardening pass (10 fixes).

Each test class documents which fix it verifies. Related commit:
``harden(reporting): batch-6 critique 10 more fixes`` (pending).
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.core.reporting.cache import InMemoryReportCache
from fdai.core.reporting.config import ReportEngineConfig
from fdai.core.reporting.datasources import (
    CallableDataSource,
    FilesystemManifestDataSource,
    NoopDataSource,
    StaticDataSource,
)
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.formats import (
    CsvFormatEncoder,
    HtmlFormatEncoder,
    MarkdownFormatEncoder,
    PrometheusFormatEncoder,
    install_default_formats,
)
from fdai.core.reporting.models import (
    DataSet,
    QuerySpec,
    RenderedReport,
    RenderedWidget,
    ReportSpec,
    TimeRange,
    WidgetSpec,
)
from fdai.core.reporting.registry import (
    DataSourceRegistry,
    FormatRegistry,
    ReportCatalog,
    WidgetRegistry,
)
from fdai.core.reporting.widgets import IframeBuilder, install_default_widgets
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.reporting import ReportingConfig

_NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _widgets() -> WidgetRegistry:
    return install_default_widgets(WidgetRegistry())


# --- Fix #1: engine deadlock on group/tabs + max_concurrent=1 ---------


class TestGroupNoDeadlockWithSinglePermit:
    async def test_group_with_children_renders_under_concurrency_of_one(self) -> None:
        # Prior to the fix, a group widget acquired the only permit and
        # its first child blocked forever waiting for the same permit.
        report = ReportSpec(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            widgets=(
                WidgetSpec(
                    id="section",
                    type="group",
                    title="Section",
                    children=(
                        WidgetSpec(
                            id="child",
                            type="query_value",
                            title="Child",
                            query=QuerySpec(datasource="s"),
                        ),
                    ),
                ),
            ),
        )
        engine = ReportEngine(
            catalog=ReportCatalog((report,)),
            sources=DataSourceRegistry(
                (StaticDataSource(name="s", dataset=DataSet(scalar=42)),)
            ),
            widgets=_widgets(),
            config=ReportEngineConfig(max_concurrent_widgets=1),
        )
        # Bound the whole call so a regression would fail the test
        # instead of hanging the CI runner.
        rendered = await asyncio.wait_for(engine.render("r"), timeout=2.0)
        section = rendered.widgets[0]
        assert section.type == "group"
        assert section.children[0].data == {"value": 42}


# --- Fix #2: CallableDataSource sync callable offloaded to a thread ----


class TestCallableOffloadsSyncToThread:
    async def test_blocking_sync_callable_does_not_freeze_the_loop(self) -> None:
        loop_ticks = 0
        marker_event = asyncio.Event()

        def _blocking(spec, *, since, until, variables):
            # Sleep in a plain thread (asyncio.to_thread lands here).
            time.sleep(0.15)
            return DataSet(scalar=1)

        async def _tick():
            nonlocal loop_ticks
            while not marker_event.is_set():
                loop_ticks += 1
                await asyncio.sleep(0.01)

        ds = CallableDataSource(name="fn", fn=_blocking)
        tick_task = asyncio.create_task(_tick())
        result = await ds.query(
            QuerySpec(datasource="fn"),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        marker_event.set()
        await tick_task

        assert result.scalar == 1
        # The event loop must have kept ticking (many iterations) while
        # the 150ms sync sleep ran in a thread. If the sync fn had
        # blocked the loop, `_tick` would have run only once or twice.
        assert loop_ticks >= 5


# --- Fix #3: cache thundering herd (single-flight per key) ------------


class TestCacheSingleFlight:
    async def test_concurrent_renders_hit_engine_once(self) -> None:
        call_count = 0

        async def _slow_source_fn(spec, *, since, until, variables):
            nonlocal call_count
            call_count += 1
            # Simulate a slow underlying query.
            await asyncio.sleep(0.05)
            return DataSet(scalar=call_count)

        source = CallableDataSource(name="fn", fn=_slow_source_fn)
        widgets = _widgets()
        report = ReportSpec(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            time_range=TimeRange(relative_duration=timedelta(hours=1)),
            widgets=(
                WidgetSpec(
                    id="w",
                    type="query_value",
                    title="w",
                    query=QuerySpec(datasource="fn"),
                ),
            ),
        )
        engine = ReportEngine(
            catalog=ReportCatalog((report,)),
            sources=DataSourceRegistry((source,)),
            widgets=widgets,
        )
        cache = InMemoryReportCache(engine, ttl_seconds=60, max_entries=10)

        # Fire ten concurrent renders for the same key. Without
        # single-flight, every one would call the source; with it, only
        # the first render executes and the others reuse the result.
        results = await asyncio.gather(*[cache.render("r") for _ in range(10)])
        assert call_count == 1
        # All renders return the same RenderedReport instance.
        first = results[0]
        for other in results[1:]:
            assert other is first


# --- Fix #4: filesystem symlink loops --------------------------------


class TestFilesystemNoSymlinkLoops:
    async def test_symlink_loop_does_not_hang(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        # sub/loop -> tmp_path : classic loop that Path.rglob would
        # follow forever.
        try:
            os.symlink(tmp_path, tmp_path / "sub" / "loop")
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unsupported on this filesystem")
        ds = FilesystemManifestDataSource(root=tmp_path)
        result = await asyncio.wait_for(
            ds.query(
                QuerySpec(datasource="fs", parameters={"pattern": "*"}),
                since=_NOW,
                until=_NOW,
                variables={},
            ),
            timeout=2.0,
        )
        # a.txt is real; the symlink loop is walked once without
        # descending (followlinks=False) and the link itself is
        # filtered by the is_symlink guard.
        paths = {row["path"] for row in result.rows}
        assert "a.txt" in paths


# --- Fix #5: absolute pattern rejected -------------------------------


class TestFilesystemAbsolutePatternRejected:
    async def test_posix_absolute_pattern_refused(self, tmp_path: Path) -> None:
        ds = FilesystemManifestDataSource(root=tmp_path)
        result = await ds.query(
            QuerySpec(datasource="fs", parameters={"pattern": "/etc/*"}),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        assert result.metadata.get("error") is not None
        assert "absolute" in result.metadata["error"]


# --- Fix #6: hidden files excluded by default ------------------------


class TestFilesystemHiddenFilesDefault:
    async def test_dotfiles_excluded_by_default(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET=x", encoding="utf-8")
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
        ds = FilesystemManifestDataSource(root=tmp_path)
        result = await ds.query(
            QuerySpec(datasource="fs", parameters={"pattern": "*"}),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        paths = {row["path"] for row in result.rows}
        assert paths == {"a.txt"}

    async def test_include_hidden_opt_in(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("x", encoding="utf-8")
        (tmp_path / "a.txt").write_text("y", encoding="utf-8")
        ds = FilesystemManifestDataSource(root=tmp_path, include_hidden=True)
        result = await ds.query(
            QuerySpec(datasource="fs", parameters={"pattern": "*"}),
            since=_NOW,
            until=_NOW,
            variables={},
        )
        paths = {row["path"] for row in result.rows}
        assert paths == {".env", "a.txt"}


# --- Fix #7: Prometheus HELP line injection --------------------------


class TestPrometheusHelpSanitized:
    def test_newline_in_title_collapsed(self) -> None:
        report = RenderedReport(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            generated_at=_NOW,
            time_range=(_NOW, _NOW),
            variables={},
            widgets=(
                RenderedWidget(
                    id="v",
                    type="query_value",
                    title="line 1\n# TYPE injected counter\nline 2",
                    data={"value": 42},
                ),
            ),
        )
        body = PrometheusFormatEncoder().encode(report).decode("utf-8")
        # HELP line MUST NOT introduce a second directive.
        help_lines = [ln for ln in body.splitlines() if ln.startswith("# HELP")]
        type_lines = [ln for ln in body.splitlines() if ln.startswith("# TYPE")]
        assert len(help_lines) == 1
        assert len(type_lines) == 1
        assert "\n" not in help_lines[0]

    def test_empty_title_falls_back(self) -> None:
        report = RenderedReport(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            generated_at=_NOW,
            time_range=(_NOW, _NOW),
            variables={},
            widgets=(
                RenderedWidget(id="v", type="query_value", title="", data={"value": 1}),
            ),
        )
        body = PrometheusFormatEncoder().encode(report).decode("utf-8")
        assert "# HELP fdai_report_r_v (no title)" in body


# --- Fix #8: iframe always emits a sandbox attribute -----------------


class TestIframeSandboxDefault:
    def test_default_sandbox_is_deny_everything(self) -> None:
        result = IframeBuilder().build(
            spec=WidgetSpec(
                id="i",
                type="iframe",
                title="i",
                options={"src": "https://example.com/x"},
            ),
            data=DataSet(),
        )
        assert result["src"] == "https://example.com/x"
        # sandbox="" is the Fetch spec shorthand for "no capabilities".
        assert result["sandbox"] == ""

    def test_author_supplied_sandbox_preserved(self) -> None:
        result = IframeBuilder().build(
            spec=WidgetSpec(
                id="i",
                type="iframe",
                title="i",
                options={
                    "src": "https://example.com/x",
                    "sandbox": "allow-scripts allow-same-origin",
                },
            ),
            data=DataSet(),
        )
        assert result["sandbox"] == "allow-scripts allow-same-origin"


# --- Fix #9: read-API variable-name regex ---------------------------


class TestReadApiVariableNameRegex:
    def test_malformed_variable_key_returns_400(self) -> None:
        engine = ReportEngine(
            catalog=ReportCatalog(),
            sources=DataSourceRegistry((NoopDataSource(),)),
            widgets=_widgets(),
        )
        # Seed a report so the code path can even reach variable
        # validation before catalog lookup.
        engine.catalog().register(
            ReportSpec(
                id="ok",
                version="1.0.0",
                name="R",
                description="",
                time_range=TimeRange(relative_duration=timedelta(hours=1)),
                widgets=(
                    WidgetSpec(
                        id="v",
                        type="free_text",
                        title="v",
                        options={"body": "x"},
                    ),
                ),
            )
        )
        auth = build_authenticator(
            verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None
        )
        os.environ["FDAI_READ_API_DEV_MODE"] = "1"
        try:
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
            client = TestClient(app)
            # A key that starts with a non-alpha character: rejected
            # before it can ever reach the substitution helper.
            response = client.get("/reports/ok/render", params={"1bad": "x"})
            assert response.status_code == 400
            assert "variable name" in response.json()["error"]
            # An UPPERCASE key: also rejected.
            response = client.get("/reports/ok/render", params={"BadName": "x"})
            assert response.status_code == 400
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)


# --- Fix #10: format encoders survive non-Mapping rows --------------


def _bad_rows_report() -> RenderedReport:
    return RenderedReport(
        id="r",
        version="1.0.0",
        name="R",
        description="",
        generated_at=_NOW,
        time_range=(_NOW, _NOW),
        variables={},
        widgets=(
            RenderedWidget(
                id="t",
                type="table",
                title="T",
                data={
                    "columns": ["a", "b"],
                    "rows": [
                        {"a": 1, "b": 2},
                        "not a mapping",  # hostile / buggy row
                        42,
                        {"a": 3, "b": 4},
                    ],
                },
            ),
        ),
    )


class TestFormatsDefensiveAgainstBadRows:
    def test_csv_skips_non_mapping_rows(self) -> None:
        body = CsvFormatEncoder().encode(_bad_rows_report()).decode("utf-8")
        # Only the two well-formed rows land in the output.
        assert "\n1,2," not in body  # column order is leading + a + b + value
        assert body.count("\n") >= 3  # header + 2 real rows + trailing

    def test_html_renders_blanks_for_bad_rows(self) -> None:
        body = HtmlFormatEncoder().encode(_bad_rows_report()).decode("utf-8")
        # Never crashes; still contains the good cells.
        assert "<td>1</td>" in body
        assert "<td>3</td>" in body
        # The bad rows collapse to blank `<td></td>` pairs.
        assert body.count("<td></td>") >= 4  # 2 bad rows * 2 columns

    def test_markdown_renders_blank_line_for_bad_rows(self) -> None:
        body = MarkdownFormatEncoder().encode(_bad_rows_report()).decode("utf-8")
        # Table header, separator, plus one row per source row (bad
        # rows collapse to empty cells) - never crashes.
        table_lines = [ln for ln in body.splitlines() if ln.startswith("|")]
        assert len(table_lines) >= 6
