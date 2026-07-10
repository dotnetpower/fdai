"""Format-encoder tests."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

from fdai.core.reporting.formats import (
    CsvFormatEncoder,
    JsonFormatEncoder,
    MarkdownFormatEncoder,
    TextFormatEncoder,
    default_format_encoders,
    install_default_formats,
)
from fdai.core.reporting.models import RenderedReport, RenderedWidget
from fdai.core.reporting.registry import FormatRegistry


def _report() -> RenderedReport:
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    return RenderedReport(
        id="ops",
        version="1.0.0",
        name="Ops Overview",
        description="Daily ops KPIs.",
        generated_at=now,
        time_range=(now - timedelta(hours=1), now),
        variables={"env": "prod"},
        widgets=(
            RenderedWidget(
                id="events",
                type="query_value",
                title="Events (1h)",
                data={"value": 1200, "unit": "events"},
            ),
            RenderedWidget(
                id="top",
                type="top_list",
                title="Top rules",
                data={
                    "columns": ["rule", "value"],
                    "rows": [
                        {"rule": "cost.idle_vm", "value": 12},
                        {"rule": "sec.public_kv", "value": 7},
                    ],
                },
            ),
            RenderedWidget(
                id="broken",
                type="table",
                title="Broken",
                data={},
                error="datasource error: RuntimeError: boom",
            ),
        ),
        tags=("ops",),
    )


class TestJsonFormat:
    def test_content_type(self) -> None:
        assert JsonFormatEncoder().content_type == "application/json"

    def test_encodes_report_to_json(self) -> None:
        body = JsonFormatEncoder().encode(_report())
        payload = json.loads(body.decode("utf-8"))
        assert payload["id"] == "ops"
        assert payload["widgets"][2]["error"].startswith("datasource error")


class TestMarkdownFormat:
    def test_renders_headings_and_body(self) -> None:
        body = MarkdownFormatEncoder().encode(_report()).decode("utf-8")
        assert body.startswith("# Ops Overview\n")
        assert "## Events (1h)" in body
        assert "**1200 events**" in body
        # Top list rendered as a markdown table.
        assert "| rule | value |" in body
        assert "| cost.idle_vm | 12 |" in body
        # Error widget rendered as blockquote, not a code block.
        assert "> ERROR: datasource error" in body

    def test_ascii_only_punctuation(self) -> None:
        body = MarkdownFormatEncoder().encode(_report()).decode("utf-8")
        # Language policy: no smart quotes, ellipsis, em/en dash, NBSP.
        for banned in ("\u2014", "\u2013", "\u2026", "\u201c", "\u201d", "\u00a0"):
            assert banned not in body


class TestCsvFormat:
    def test_headers_and_rows(self) -> None:
        body = CsvFormatEncoder().encode(_report()).decode("utf-8")
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
        header = reader.fieldnames or []
        assert set(header) >= {
            "widget_id",
            "widget_title",
            "widget_type",
            "rule",
            "value",
        }
        by_widget: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            by_widget.setdefault(row["widget_id"], []).append(row)
        # The top-list widget contributes 2 rows.
        assert len(by_widget["top"]) == 2
        # The scalar widget flattens to one row with the value.
        assert by_widget["events"][0]["value"] == "1200"


class TestTextFormat:
    def test_content_type_is_plain_utf8(self) -> None:
        enc = TextFormatEncoder()
        assert enc.name == "text"
        assert enc.content_type == "text/plain; charset=utf-8"

    def test_header_variables_and_widget_types(self) -> None:
        body = TextFormatEncoder().encode(_report()).decode("utf-8")
        # Header block.
        assert body.startswith("# Ops Overview\n")
        assert "id: ops  version: 1.0.0" in body
        assert "window: 2026-07-10T11:00:00+00:00 .. 2026-07-10T12:00:00+00:00" in body
        # variables line (was uncovered).
        assert "variables: env=prod" in body
        # query_value widget renders its scalar.
        assert "value: 1200" in body
        # top_list renders as a pipe-joined table with a header row.
        assert "rule | value" in body
        assert "cost.idle_vm | 12" in body
        # error widget short-circuits to an ERROR line.
        assert "ERROR: datasource error: RuntimeError: boom" in body

    def test_free_text_group_and_unknown_widget_branches(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = RenderedReport(
            id="misc",
            version="1.0.0",
            name="Misc",
            description="",
            generated_at=now,
            time_range=(now - timedelta(hours=1), now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="note",
                    type="free_text",
                    title="Note",
                    data={"body": "line one\nline two"},
                ),
                RenderedWidget(
                    id="grp",
                    type="group",
                    title="Group",
                    data={},
                    children=(
                        RenderedWidget(
                            id="child",
                            type="query_value",
                            title="Child",
                            data={"value": 42},
                        ),
                    ),
                ),
                RenderedWidget(
                    id="mystery",
                    type="sankey",
                    title="Mystery",
                    data={"flows": 3},
                ),
                RenderedWidget(
                    id="empty",
                    type="heatmap",
                    title="Empty",
                    data={},
                ),
            ),
            tags=(),
        )
        body = TextFormatEncoder().encode(report).decode("utf-8")
        # free_text splits body lines and indents each.
        assert "line one" in body
        assert "line two" in body
        # group recurses into children at a deeper heading level.
        assert "- Child" in body
        assert "value: 42" in body
        # unknown type with a summary key -> compact (type: key=value).
        assert "(sankey: flows=3)" in body
        # unknown type with empty data -> compact (type: {}) fallback.
        assert "(heatmap: {})" in body
        # No variables line when variables is empty.
        assert "variables:" not in body

    def test_table_without_columns_and_row_truncation(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = RenderedReport(
            id="tbl",
            version="1.0.0",
            name="Tables",
            description="",
            generated_at=now,
            time_range=(now - timedelta(hours=1), now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="nocols",
                    type="table",
                    title="No columns",
                    data={"note": "raw"},
                ),
                RenderedWidget(
                    id="big",
                    type="table",
                    title="Big",
                    data={
                        # 'opt' is absent from every row -> exercises the
                        # None-cell -> empty-string branch.
                        "columns": ["n", "opt"],
                        "rows": [{"n": i} for i in range(55)],
                    },
                ),
            ),
            tags=(),
        )
        body = TextFormatEncoder().encode(report).decode("utf-8")
        # Table without columns falls back to a repr of the mapping.
        assert "'note': 'raw'" in body
        # Only the first 50 rows render, then a truncation marker.
        assert "... (5 more rows)" in body
        # The header carries both columns, and a missing 'opt' renders as
        # an empty trailing cell (row '0 | '), never the literal 'None'.
        assert "n | opt" in body
        assert "0 | " in body
        assert "| None" not in body

    def test_ascii_only_punctuation(self) -> None:
        body = TextFormatEncoder().encode(_report()).decode("utf-8")
        for banned in ("\u2014", "\u2013", "\u2026", "\u201c", "\u201d", "\u00a0"):
            assert banned not in body


class TestFormatRegistry:
    def test_defaults_registered_by_name(self) -> None:
        names = {e.name for e in default_format_encoders()}
        assert {"json", "markdown", "csv"} <= names

    def test_install_default_formats_is_idempotent(self) -> None:
        registry = FormatRegistry()
        install_default_formats(registry)
        install_default_formats(registry)  # re-install must not fail
        assert {"csv", "json", "markdown"} <= set(registry.names())
