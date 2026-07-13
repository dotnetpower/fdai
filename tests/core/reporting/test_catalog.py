"""Catalog-loader tests: schema validation + duration parsing + duplicates."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.reporting.catalog import (
    ReportCatalogError,
    default_report_schema_path,
    load_report_catalog,
    load_report_from_mapping,
)
from fdai.core.reporting.widgets import default_widget_builders


def _base_widget_types() -> frozenset[str]:
    return frozenset({b.type_name for b in default_widget_builders()} | {"group"})


class TestLoadReportFromMapping:
    def test_valid_last_alias_becomes_relative_duration(self) -> None:
        raw = {
            "id": "demo",
            "version": "1.0.0",
            "name": "Demo",
            "time_range": {"last": "6h"},
            "widgets": [
                {
                    "id": "v",
                    "type": "query_value",
                    "title": "V",
                    "query": {"datasource": "audit", "parameters": {"projection": "count_total"}},
                }
            ],
        }
        spec = load_report_from_mapping(raw)
        assert spec.id == "demo"
        assert spec.time_range.relative_duration is not None
        assert spec.time_range.relative_duration.total_seconds() == 6 * 3600
        assert spec.widgets[0].type == "query_value"

    def test_variable_defaults_parsed(self) -> None:
        raw = {
            "id": "demo",
            "version": "1.0.0",
            "name": "Demo",
            "time_range": {"last": "1d"},
            "variables": [{"name": "env", "default": "prod", "values": ["prod", "staging"]}],
            "widgets": [
                {"id": "t", "type": "free_text", "title": "Intro", "options": {"body": "hi"}}
            ],
        }
        spec = load_report_from_mapping(raw)
        assert spec.variables[0].name == "env"
        assert spec.variables[0].values == ("prod", "staging")

    def test_group_widget_recurses(self) -> None:
        raw = {
            "id": "grp",
            "version": "1.0.0",
            "name": "Grp",
            "time_range": {"last": "1d"},
            "widgets": [
                {
                    "id": "section",
                    "type": "group",
                    "title": "Section",
                    "children": [
                        {
                            "id": "child",
                            "type": "free_text",
                            "title": "child",
                            "options": {"body": "x"},
                        }
                    ],
                }
            ],
        }
        spec = load_report_from_mapping(raw, allowed_widget_types=_base_widget_types())
        assert spec.widgets[0].type == "group"
        assert spec.widgets[0].children[0].id == "child"

    def test_unknown_top_level_key_rejected(self) -> None:
        raw = {
            "id": "demo",
            "version": "1.0.0",
            "name": "Demo",
            "time_range": {"last": "1d"},
            "widgets": [{"id": "v", "type": "free_text", "title": "V", "options": {"body": "hi"}}],
            "typo": True,
        }
        with pytest.raises(ReportCatalogError, match="typo"):
            load_report_from_mapping(raw)

    def test_missing_time_range_rejected(self) -> None:
        raw = {
            "id": "demo",
            "version": "1.0.0",
            "name": "Demo",
            "widgets": [{"id": "v", "type": "free_text", "title": "V", "options": {"body": "hi"}}],
        }
        with pytest.raises(ReportCatalogError, match="time_range"):
            load_report_from_mapping(raw)

    def test_bad_duration_pattern_rejected(self) -> None:
        raw = {
            "id": "demo",
            "version": "1.0.0",
            "name": "Demo",
            "time_range": {"last": "1x"},
            "widgets": [{"id": "v", "type": "free_text", "title": "V", "options": {"body": "hi"}}],
        }
        with pytest.raises(ReportCatalogError, match="last|1x"):
            load_report_from_mapping(raw)

    def test_allowlists_reject_unknown_widget_and_datasource(self) -> None:
        raw = {
            "id": "demo",
            "version": "1.0.0",
            "name": "Demo",
            "time_range": {"last": "1d"},
            "widgets": [
                {
                    "id": "v",
                    "type": "made_up_widget",
                    "title": "V",
                    "query": {"datasource": "made_up_source"},
                }
            ],
        }
        with pytest.raises(ReportCatalogError) as exc_info:
            load_report_from_mapping(
                raw,
                allowed_widget_types=_base_widget_types(),
                allowed_datasources=frozenset({"audit"}),
            )
        joined = str(exc_info.value)
        assert "made_up_widget" in joined
        assert "made_up_source" in joined


class TestLoadReportCatalog:
    def test_ships_upstream_reports_load_and_are_unique(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        reports_dir = repo_root / "rule-catalog" / "reports"
        specs = load_report_catalog(
            reports_dir,
            allowed_widget_types=_base_widget_types(),
            allowed_datasources=frozenset(
                {
                    "audit",
                    "report_feed",
                    "metric",
                    "log_query",
                    "ontology",
                    "static",
                    "noop",
                }
            ),
        )
        ids = {s.id for s in specs}
        assert {"shadow-mode-daily", "signal-feed-overview", "metric-explorer"} <= ids

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        specs = load_report_catalog(tmp_path / "nope")
        assert specs == ()

    def test_duplicate_id_across_files_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text(
            """
id: dup
version: 1.0.0
name: A
time_range:
  last: 1d
widgets:
  - id: v
    type: free_text
    title: V
    options: {body: hi}
""",
            encoding="utf-8",
        )
        (tmp_path / "b.yaml").write_text(
            """
id: dup
version: 1.0.0
name: B
time_range:
  last: 1d
widgets:
  - id: v
    type: free_text
    title: V
    options: {body: hi}
""",
            encoding="utf-8",
        )
        with pytest.raises(ReportCatalogError, match="duplicate report id"):
            load_report_catalog(tmp_path)

    def test_two_yaml_documents_in_one_file_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "multi.yaml").write_text(
            """
id: a
version: 1.0.0
name: A
time_range:
  last: 1d
widgets:
  - id: v
    type: free_text
    title: V
    options: {body: hi}
---
id: b
version: 1.0.0
name: B
time_range:
  last: 1d
widgets:
  - id: v
    type: free_text
    title: V
    options: {body: hi}
""",
            encoding="utf-8",
        )
        with pytest.raises(ReportCatalogError, match="single YAML document"):
            load_report_catalog(tmp_path)


def test_default_schema_path_exists() -> None:
    path = default_report_schema_path()
    assert path.exists(), path
