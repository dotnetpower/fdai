"""Integration tests for the reporting read-API routes."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai.core.reporting.catalog import load_report_catalog
from fdai.core.reporting.datasources import (
    AuditDataSource,
    NoopDataSource,
    StaticDataSource,
)
from fdai.core.reporting.engine import ReportEngine
from fdai.core.reporting.formats import install_default_formats
from fdai.core.reporting.models import DataSet, Series
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
from fdai.delivery.read_api.routes.reporting import ReportingConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "rule-catalog" / "reports"


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _widgets() -> WidgetRegistry:
    return install_default_widgets(WidgetRegistry())


def _formats() -> FormatRegistry:
    return install_default_formats(FormatRegistry())


def _seeded_reader() -> InMemoryConsoleReadModel:
    reader = InMemoryConsoleReadModel()
    for i in range(3):
        reader.record_audit_entry(
            {"event_id": f"00000000-0000-0000-0000-{i:012d}"},
            actor="thor",
            action_kind="execute_action",
            mode="shadow",
        )
    return reader


def _build_engine(
    *,
    reports_root: Path | None = None,
) -> tuple[ReportEngine, InMemoryConsoleReadModel]:
    reader = _seeded_reader()
    sources = DataSourceRegistry(
        (
            AuditDataSource(reader=reader),
            StaticDataSource(
                name="static_series",
                dataset=DataSet(
                    series=(
                        Series(
                            label="a",
                            points=((1.0, 10.0), (2.0, 20.0)),
                        ),
                    )
                ),
            ),
            # Upstream sample reports reference these two names; wire
            # them as noop stubs so the sample catalog validates when a
            # real backend is not yet bound.
            NoopDataSource(name="report_feed"),
            NoopDataSource(name="metric"),
            NoopDataSource(name="log_query"),
            NoopDataSource(name="ontology"),
        )
    )
    widgets = _widgets()
    if reports_root is not None:
        specs = load_report_catalog(
            reports_root,
            allowed_widget_types=frozenset(widgets.types()) | {"group"},
            allowed_datasources=frozenset(sources.names()),
        )
        catalog = ReportCatalog(specs)
    else:
        catalog = ReportCatalog()
    engine = ReportEngine(catalog=catalog, sources=sources, widgets=widgets)
    return engine, reader


def _client(engine: ReportEngine) -> TestClient:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=_seeded_reader(),
        config=ReadApiConfig(
            dev_mode=True,
            reporting=ReportingConfig(engine=engine, formats=_formats()),
        ),
    )
    return TestClient(app)


class TestReportingRoutes:
    def test_list_reports_returns_ships_upstream(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get("/reports")
        assert response.status_code == 200
        payload = response.json()
        ids = {item["id"] for item in payload["items"]}
        assert {"shadow-mode-daily", "signal-feed-overview", "metric-explorer"} <= ids
        assert {"csv", "json", "markdown"} <= set(payload["formats"])

    def test_registry_lists_wired_names(self) -> None:
        engine, _ = _build_engine()
        client = _client(engine)
        response = client.get("/reports/registry")
        assert response.status_code == 200
        payload = response.json()
        assert {"audit", "static_series"} <= set(payload["datasources"])
        assert "timeseries" in payload["widgets"]
        assert {"csv", "json", "markdown"} <= set(payload["formats"])

    def test_get_report_definition_returns_full_spec(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get("/reports/shadow-mode-daily")
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == "shadow-mode-daily"
        assert payload["widget_count"] >= 5
        # The endpoint reports absolute widget IDs so a downstream FE
        # can wire click-through without re-parsing the YAML.
        widget_ids = {w["id"] for w in payload["widgets"]}
        assert "total-shadow" in widget_ids

    def test_get_report_definition_returns_404_for_unknown(self) -> None:
        engine, _ = _build_engine()
        client = _client(engine)
        response = client.get("/reports/does-not-exist")
        assert response.status_code == 404
        assert "not found" in response.json()["error"]

    def test_render_default_format_is_json(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get("/reports/shadow-mode-daily/render")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        payload = json.loads(response.content.decode("utf-8"))
        assert payload["id"] == "shadow-mode-daily"
        assert any(w["id"] == "total-shadow" for w in payload["widgets"])

    def test_render_markdown_format(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get("/reports/shadow-mode-daily/render", params={"format": "markdown"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert response.content.startswith(b"# Shadow-Mode Daily Rollup")

    def test_render_csv_format(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get("/reports/shadow-mode-daily/render", params={"format": "csv"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8")))
        rows = list(reader)
        assert reader.fieldnames is not None
        assert "widget_id" in reader.fieldnames
        widget_ids = {row["widget_id"] for row in rows}
        assert "total-shadow" in widget_ids

    def test_render_unknown_format_is_400(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get("/reports/shadow-mode-daily/render", params={"format": "pdf"})
        assert response.status_code == 400
        assert "pdf" in response.json()["error"]

    def test_render_missing_report_returns_404(self) -> None:
        engine, _ = _build_engine()
        client = _client(engine)
        response = client.get("/reports/nope/render")
        assert response.status_code == 404

    def test_render_rejects_unknown_variable(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get(
            "/reports/shadow-mode-daily/render",
            params={"env": "prod"},  # not declared on this report
        )
        assert response.status_code == 400

    def test_render_accepts_declared_variable(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.get(
            "/reports/signal-feed-overview/render",
            params={"category": "workload"},
        )
        assert response.status_code == 200
        payload = json.loads(response.content.decode("utf-8"))
        assert payload["variables"] == {"category": "workload"}


class TestReadOnlyInvariant:
    def test_post_render_is_405(self) -> None:
        engine, _ = _build_engine(reports_root=REPORTS_ROOT)
        client = _client(engine)
        response = client.post("/reports/shadow-mode-daily/render")
        # Starlette returns 405 for a POST on a GET-only route.
        assert response.status_code == 405

    def test_post_list_is_405(self) -> None:
        engine, _ = _build_engine()
        client = _client(engine)
        response = client.post("/reports")
        assert response.status_code == 405


class TestConfigValidation:
    def test_prefix_collision_with_core_route_fails_fast(self) -> None:
        engine, _ = _build_engine()
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
        with pytest.raises(ValueError, match="collides with a core route"):
            build_app(
                authenticator=auth,
                read_model=_seeded_reader(),
                config=ReadApiConfig(
                    dev_mode=True,
                    reporting=ReportingConfig(engine=engine, formats=_formats(), prefix="/audit"),
                ),
            )

    def test_unknown_default_format_fails_fast(self) -> None:
        engine, _ = _build_engine()
        auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
        with pytest.raises(ValueError, match="default_format"):
            build_app(
                authenticator=auth,
                read_model=_seeded_reader(),
                config=ReadApiConfig(
                    dev_mode=True,
                    reporting=ReportingConfig(
                        engine=engine, formats=_formats(), default_format="pdf"
                    ),
                ),
            )
