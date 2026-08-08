"""Format-encoder tests."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

from fdai.core.reporting.formats import (
    CsvFormatEncoder,
    HtmlFormatEncoder,
    JsonFormatEncoder,
    MarkdownFormatEncoder,
    NdjsonFormatEncoder,
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

    def test_free_text_note_group_and_no_column_table(self) -> None:
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
                RenderedWidget(id="ft", type="free_text", title="Note", data={"body": "hello"}),
                RenderedWidget(
                    id="nt",
                    type="note",
                    title="Warn",
                    data={"severity": "high", "body": "watch out"},
                ),
                RenderedWidget(
                    id="grp",
                    type="group",
                    title="Group",
                    data={},
                    children=(
                        RenderedWidget(
                            id="k",
                            type="query_value",
                            title="Kid",
                            data={"value": 7},
                        ),
                    ),
                ),
                RenderedWidget(id="nc", type="table", title="NoCols", data={"note": "raw"}),
                RenderedWidget(
                    id="ht",
                    type="table",
                    title="Hostile",
                    data={"columns": ["c"], "rows": [{"c": "ok"}, "not-a-mapping"]},
                ),
                RenderedWidget(id="myst", type="sankey", title="Myst", data={"flows": 3}),
            ),
            tags=(),
        )
        body = MarkdownFormatEncoder().encode(report).decode("utf-8")
        # free_text body rendered verbatim.
        assert "hello" in body
        # note rendered as a severity-tagged blockquote.
        assert "> (high) watch out" in body
        # group recurses into children at a deeper heading level.
        assert "### Kid" in body
        assert "**7**" in body
        # table without columns falls back to a fenced json block.
        assert "```json" in body
        assert '"note": "raw"' in body
        # A non-Mapping row renders as a blank cell instead of crashing.
        assert "| ok |" in body
        # An unknown widget type falls back to a fenced json block.
        assert '"flows": 3' in body


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


class TestHtmlFormat:
    def test_content_type_is_html_utf8(self) -> None:
        enc = HtmlFormatEncoder()
        assert enc.name == "html"
        assert enc.content_type == "text/html; charset=utf-8"

    def test_header_meta_and_core_widget_types(self) -> None:
        body = HtmlFormatEncoder().encode(_report()).decode("utf-8")
        # Header + description (description branch was uncovered).
        assert "<h1>Ops Overview</h1>" in body
        assert "<p>Daily ops KPIs.</p>" in body
        assert "report_id: <code>ops</code>" in body
        # query_value -> <strong>.
        assert "<strong>1200</strong>" in body
        # top_list -> real <table> with escaped headers.
        assert "<th>rule</th>" in body
        assert "<td>cost.idle_vm</td>" in body
        # error widget -> fdai-error div, no table.
        assert "<div class='fdai-error'>datasource error: RuntimeError: boom</div>" in body

    def test_html_escaping_of_hostile_cells(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = RenderedReport(
            id="x",
            version="1",
            name="<script>alert(1)</script>",
            description="",
            generated_at=now,
            time_range=(now - timedelta(hours=1), now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="t",
                    type="table",
                    title="T",
                    data={
                        "columns": ["c"],
                        "rows": [{"c": "<b>x</b>"}, {"c": None}, "not-a-mapping"],
                    },
                ),
            ),
            tags=(),
        )
        body = HtmlFormatEncoder().encode(report).decode("utf-8")
        # Report name and cell content are HTML-escaped, not injected raw.
        assert "<script>" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        assert "&lt;b&gt;x&lt;/b&gt;" in body
        # A None cell renders as an empty <td>.
        assert "<td></td>" in body
        # A non-Mapping row emits blank cells instead of crashing.
        assert body.count("<tr>") >= 3

    def test_free_text_group_unknown_and_no_column_table(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = RenderedReport(
            id="m",
            version="1",
            name="M",
            description="",
            generated_at=now,
            time_range=(now - timedelta(hours=1), now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="note",
                    type="free_text",
                    title="Note",
                    data={"body": "<hi>"},
                ),
                RenderedWidget(
                    id="grp",
                    type="tabs",
                    title="Tabs",
                    data={},
                    children=(
                        RenderedWidget(
                            id="c",
                            type="query_value",
                            title="C",
                            data={"value": 9},
                        ),
                    ),
                ),
                RenderedWidget(
                    id="u",
                    type="sankey",
                    title="U",
                    data={"flows": 2},
                ),
                RenderedWidget(
                    id="nocols",
                    type="table",
                    title="NoCols",
                    data={"note": "raw"},
                ),
            ),
            tags=(),
        )
        body = HtmlFormatEncoder().encode(report).decode("utf-8")
        # free_text body is escaped inside <pre>.
        assert "<pre>&lt;hi&gt;</pre>" in body
        # tabs recurses into children.
        assert "<strong>9</strong>" in body
        # unknown type falls back to a pretty-printed JSON <pre> (HTML-escaped).
        assert "&quot;flows&quot;: 2" in body
        # table without columns falls back to JSON <pre>, not a <table>.
        assert "&quot;note&quot;: &quot;raw&quot;" in body


class TestNdjsonFormat:
    def test_content_type_is_ndjson(self) -> None:
        enc = NdjsonFormatEncoder()
        assert enc.name == "ndjson"
        assert enc.content_type == "application/x-ndjson"

    def test_header_line_then_one_object_per_widget(self) -> None:
        body = NdjsonFormatEncoder().encode(_report()).decode("utf-8")
        lines = [json.loads(line) for line in body.splitlines()]
        # Trailing newline -> no empty final element after splitlines.
        assert body.endswith("\n")
        # First line is the report header (no widgets embedded).
        assert lines[0]["kind"] == "report"
        assert lines[0]["id"] == "ops"
        assert "widgets" not in lines[0]
        # Remaining lines are one widget object each.
        widget_lines = [entry for entry in lines[1:] if entry["kind"] == "widget"]
        assert {w["id"] for w in widget_lines} >= {"events", "top", "broken"}
        # The error widget carries its error string on its own line.
        broken = next(w for w in widget_lines if w["id"] == "broken")
        assert broken["error"].startswith("datasource error")

    def test_group_children_flatten_with_parent_pointer(self) -> None:
        now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        report = RenderedReport(
            id="g",
            version="1",
            name="G",
            description="",
            generated_at=now,
            time_range=(now - timedelta(hours=1), now),
            variables={},
            widgets=(
                RenderedWidget(
                    id="grp",
                    type="group",
                    title="Group",
                    data={},
                    children=(
                        RenderedWidget(
                            id="kid",
                            type="query_value",
                            title="Kid",
                            data={"value": 7},
                        ),
                    ),
                ),
            ),
            tags=(),
        )
        body = NdjsonFormatEncoder().encode(report).decode("utf-8")
        entries = {
            e["id"]: e
            for e in (json.loads(line) for line in body.splitlines())
            if e["kind"] == "widget"
        }
        # Parent group emitted with no parent pointer.
        assert "parent" not in entries["grp"]
        # Child flattened onto its own line, pointing back at the group.
        assert entries["kid"]["parent"] == "grp"
        assert entries["kid"]["data"]["value"] == 7


class TestFormatRegistry:
    def test_defaults_registered_by_name(self) -> None:
        names = {e.name for e in default_format_encoders()}
        assert {"json", "markdown", "csv"} <= names

    def test_install_default_formats_is_idempotent(self) -> None:
        registry = FormatRegistry()
        install_default_formats(registry)
        install_default_formats(registry)  # re-install must not fail
        assert {"csv", "json", "markdown"} <= set(registry.names())
