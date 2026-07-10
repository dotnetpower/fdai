"""Tests for the 10-item batch-5 hardening pass.

Each test class documents which risk it verifies. See
`docs/roadmap/reporting-subsystem.md` for the Safety and invariants section.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.reporting.catalog import (
    ReportCatalogError,
    load_report_catalog,
    load_report_from_mapping,
)
from fdai.core.reporting.config import ReportEngineConfig
from fdai.core.reporting.contracts import VariableRejectedError
from fdai.core.reporting.datasources import StaticDataSource
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.formats import CsvFormatEncoder, MarkdownFormatEncoder
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
    ReportCatalog,
    WidgetRegistry,
)
from fdai.core.reporting.substitution import substitute
from fdai.core.reporting.widgets import ImageBuilder, install_default_widgets

# --- shared helpers ------------------------------------------------------


class _RecordingDataSource:
    def __init__(self, name: str, dataset: DataSet | None = None) -> None:
        self._name = name
        self._dataset = dataset or DataSet(scalar=0)
        self.calls: list[Mapping[str, object]] = []

    @property
    def name(self) -> str:
        return self._name

    async def query(self, spec, *, since, until, variables):
        self.calls.append(
            {"params": dict(spec.parameters), "variables": dict(variables)}
        )
        return self._dataset


class _HangingDataSource:
    def __init__(self, name: str = "hang") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def query(self, *_args, **_kwargs):
        await asyncio.sleep(5)  # longer than any test's timeout
        return DataSet()


def _spec_now() -> datetime:
    return datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _report_with(*widgets, variables=()) -> ReportSpec:
    return ReportSpec(
        id="r",
        version="1.0.0",
        name="R",
        description="",
        time_range=TimeRange(relative_duration=timedelta(hours=1)),
        variables=tuple(variables),
        widgets=tuple(widgets),
    )


def _engine(
    *,
    sources: tuple = (),
    reports: tuple[ReportSpec, ...] = (),
    config: ReportEngineConfig | None = None,
) -> ReportEngine:
    widgets = install_default_widgets(WidgetRegistry())
    return ReportEngine(
        catalog=ReportCatalog(reports),
        sources=DataSourceRegistry(sources),
        widgets=widgets,
        clock=lambda: _spec_now(),
        config=config,
    )


# --- Risk #1: CSV formula injection ------------------------------------


class TestCsvFormulaInjection:
    def test_leading_formula_triggers_are_prefixed(self) -> None:
        now = _spec_now()
        report = RenderedReport(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            generated_at=now,
            time_range=(now, now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="t",
                    type="table",
                    title="T",
                    data={
                        "columns": ["cell"],
                        "rows": [
                            {"cell": "=SUM(A1:A5)"},
                            {"cell": "+CMD"},
                            {"cell": "-1"},
                            {"cell": "@EVIL"},
                            {"cell": "\tTAB"},
                            {"cell": "safe"},
                        ],
                    },
                ),
            ),
        )
        body = CsvFormatEncoder().encode(report).decode("utf-8")
        assert "'=SUM(A1:A5)" in body
        assert "'+CMD" in body
        assert "'-1" in body
        assert "'@EVIL" in body
        assert "safe" in body

    def test_non_trigger_values_unchanged(self) -> None:
        now = _spec_now()
        report = RenderedReport(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            generated_at=now,
            time_range=(now, now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="t",
                    type="table",
                    title="T",
                    data={
                        "columns": ["cell"],
                        "rows": [{"cell": "normal value 123"}],
                    },
                ),
            ),
        )
        body = CsvFormatEncoder().encode(report).decode("utf-8")
        assert "'normal" not in body


# --- Risk #2: Markdown HTML injection ---------------------------------


class TestMarkdownHtmlEscape:
    def test_html_special_chars_escaped_in_cells(self) -> None:
        now = _spec_now()
        report = RenderedReport(
            id="r",
            version="1.0.0",
            name="R",
            description="",
            generated_at=now,
            time_range=(now, now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="t",
                    type="table",
                    title="T",
                    data={
                        "columns": ["msg"],
                        "rows": [{"msg": "<script>alert(1)</script> & <b>bold</b>"}],
                    },
                ),
            ),
        )
        body = MarkdownFormatEncoder().encode(report).decode("utf-8")
        assert "<script>" not in body
        assert "&lt;script&gt;" in body
        assert "&amp;" in body


# --- Risk #3: Image extension allowlist -------------------------------


class TestImageExtensionAllowlist:
    def test_svg_rejected_even_over_https(self) -> None:
        result = ImageBuilder().build(
            spec=WidgetSpec(
                id="i",
                type="image",
                title="i",
                options={"src": "https://cdn.example.com/x.svg", "alt": "x"},
            ),
            data=DataSet(),
        )
        assert result["src"] is None
        assert "extension" in result["error"]

    def test_png_allowed(self) -> None:
        result = ImageBuilder().build(
            spec=WidgetSpec(
                id="i",
                type="image",
                title="i",
                options={"src": "https://cdn.example.com/x.png", "alt": "x"},
            ),
            data=DataSet(),
        )
        assert result["src"] == "https://cdn.example.com/x.png"

    def test_unknown_extension_rejected(self) -> None:
        result = ImageBuilder().build(
            spec=WidgetSpec(
                id="i",
                type="image",
                title="i",
                options={"src": "https://cdn.example.com/x.exe", "alt": "x"},
            ),
            data=DataSet(),
        )
        assert result["src"] is None


# --- Risk #4: Per-widget timeout --------------------------------------


class TestPerWidgetTimeout:
    async def test_hanging_source_becomes_timeout_error(self) -> None:
        report = _report_with(
            WidgetSpec(
                id="w",
                type="query_value",
                title="w",
                query=QuerySpec(datasource="hang"),
            )
        )
        engine = _engine(
            sources=(_HangingDataSource(),),
            reports=(report,),
            config=ReportEngineConfig(per_widget_timeout_seconds=0.05),
        )
        rendered = await engine.render("r")
        assert rendered.widgets[0].error is not None
        assert "timeout" in rendered.widgets[0].error


# --- Risk #5: Variable substitution in query parameters ---------------


class TestVariableSubstitution:
    def test_pure_helper_replaces_all_syntaxes(self) -> None:
        result = substitute(
            {
                "name": "$env",
                "brace": "${env}",
                "middle": "prod-$env-vm",
                "escaped": "$$literal",
                "nested": {"deep": ["${env}", "x"]},
                "typed": 42,
            },
            {"env": "prod"},
        )
        assert result == {
            "name": "prod",
            "brace": "prod",
            "middle": "prod-prod-vm",
            "escaped": "$literal",
            "nested": {"deep": ["prod", "x"]},
            "typed": 42,
        }

    def test_undeclared_variable_raises(self) -> None:
        with pytest.raises(VariableRejectedError, match="undeclared"):
            substitute("hello $missing", {})

    async def test_engine_substitutes_parameters(self) -> None:
        source = _RecordingDataSource("s")
        report = _report_with(
            WidgetSpec(
                id="w",
                type="query_value",
                title="w",
                query=QuerySpec(
                    datasource="s",
                    parameters={"env_name": "$env", "raw": 7},
                ),
            ),
            variables=(Variable(name="env", default="prod"),),
        )
        engine = _engine(sources=(source,), reports=(report,))
        await engine.render("r")
        assert source.calls[0]["params"] == {"env_name": "prod", "raw": 7}


# --- Risk #6: Catalog loader size guards ------------------------------


class TestCatalogSizeGuards:
    def test_max_widgets_per_report_from_mapping(self) -> None:
        widgets = [
            {"id": f"w{i}", "type": "free_text", "title": "t", "options": {"body": "x"}}
            for i in range(200)
        ]
        raw = {
            "id": "big",
            "version": "1.0.0",
            "name": "big",
            "time_range": {"last": "1d"},
            "widgets": widgets,
        }
        with pytest.raises(ReportCatalogError, match="widget tree size"):
            load_report_from_mapping(raw, max_widgets_per_report=10)

    def test_max_file_size_rejects_large_files(self, tmp_path: Path) -> None:
        (tmp_path / "big.yaml").write_text("x" * 4096, encoding="utf-8")
        with pytest.raises(ReportCatalogError, match="file size"):
            load_report_catalog(tmp_path, max_file_size_bytes=1024)

    def test_max_files_rejects_bulky_directory(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"r{i}.yaml").write_text(
                f"""
id: r{i}
version: 1.0.0
name: r{i}
time_range:
  last: 1d
widgets:
  - id: v
    type: free_text
    title: V
    options: {{body: x}}
""".strip(),
                encoding="utf-8",
            )
        with pytest.raises(ReportCatalogError, match="max_files"):
            load_report_catalog(tmp_path, max_files=3)


# --- Risk #7: read-API report_id validation ---------------------------


class TestReportIdValidation:
    def test_malformed_report_id_returns_400(self) -> None:
        # Integration: use TestClient with build_app + reporting config.
        import os

        from starlette.testclient import TestClient

        from fdai.core.reporting.formats import install_default_formats
        from fdai.core.reporting.registry import FormatRegistry
        from fdai.delivery.read_api.auth import build_authenticator
        from fdai.delivery.read_api.main import ReadApiConfig, build_app
        from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
        from fdai.delivery.read_api.reporting import ReportingConfig

        engine = _engine()
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
            response = client.get("/reports/UPPERCASE")
            assert response.status_code == 400
            assert "malformed" in response.json()["error"]
            response = client.get("/reports/x/render", params={"format": "..%2f"})
            assert response.status_code == 400
        finally:
            os.environ.pop("FDAI_READ_API_DEV_MODE", None)


# --- Risk #8: RenderedWidget error length cap -------------------------


class TestErrorMessageCap:
    async def test_long_error_truncated(self) -> None:
        long_msg = "x" * 5000

        class _BomberSource:
            name = "bomb"

            async def query(self, *_args, **_kwargs):
                raise RuntimeError(long_msg)

        report = _report_with(
            WidgetSpec(
                id="w",
                type="query_value",
                title="w",
                query=QuerySpec(datasource="bomb"),
            )
        )
        engine = _engine(
            sources=(_BomberSource(),),
            reports=(report,),
            config=ReportEngineConfig(max_error_message_chars=200),
        )
        rendered = await engine.render("r")
        error = rendered.widgets[0].error
        assert error is not None
        assert len(error) <= 200
        assert "truncated" in error


# --- Risk #9: Audit datasource tz-aware datetime comparison -----------


class TestAuditTzAware:
    async def test_naive_since_treated_as_utc(self) -> None:
        from fdai.core.reporting.datasources.audit import AuditDataSource
        from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel

        reader = InMemoryConsoleReadModel()
        # tz-aware recorded_at
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        reader.record_audit_entry(
            {
                "event_id": "00000000-0000-0000-0000-000000000000",
                "recorded_at": now.isoformat(),
            },
            actor="thor",
            action_kind="k",
            mode="shadow",
        )
        ds = AuditDataSource(reader=reader)
        # Naive datetimes must be treated as UTC (no silent exclusion).
        result = await ds.query(
            QuerySpec(datasource="audit", parameters={"projection": "count_total"}),
            since=datetime(2026, 7, 10, 11, 0),  # naive
            until=datetime(2026, 7, 10, 13, 0),  # naive
            variables={},
        )
        assert result.scalar == 1


# --- Risk #10: RenderedReport widget-count cap -----------------------


class TestWidgetCountCap:
    async def test_oversized_report_replaced_with_sentinel(self) -> None:
        # Sneak past the loader by constructing the spec directly.
        widgets = tuple(
            WidgetSpec(id=f"w{i}", type="free_text", title="t", options={"body": "x"})
            for i in range(50)
        )
        engine = _engine(
            reports=(_report_with(*widgets),),
            config=ReportEngineConfig(max_widgets_per_report=10),
        )
        rendered = await engine.render("r")
        assert len(rendered.widgets) == 1
        sentinel = rendered.widgets[0]
        assert sentinel.error is not None
        assert "max_widgets_per_report" in sentinel.error


# --- Engine health surface (bonus) -----------------------------------


class TestEngineHealth:
    def test_health_lists_registrations(self) -> None:
        engine = _engine(sources=(StaticDataSource(name="s", dataset=DataSet()),))
        payload = engine.health()
        assert payload["reports"] == 0
        assert "s" in payload["datasources"]
        assert "timeseries" in payload["widget_types"]
        assert isinstance(payload["config"], dict)
