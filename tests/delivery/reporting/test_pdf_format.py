"""Delivery-side PDF report encoder tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.reporting.models import RenderedReport, RenderedWidget
from fdai.core.reporting.registry import FormatRegistry
from fdai.delivery.reporting.pdf_format import (
    PdfFormatEncoder,
    install_pdf_format,
    render_report_html,
)


def _report() -> RenderedReport:
    return RenderedReport(
        id="incident-rca-dossier",
        version="1.0.0",
        name="Incident RCA Dossier",
        description="Grounded incident evidence and response history.",
        generated_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
        time_range=(
            datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
            datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
        ),
        variables={"correlation_id": "corr-example"},
        widgets=(
            RenderedWidget(
                id="evidence-record-count",
                type="query_value",
                title="Correlated records",
                data={"value": 7, "unit": "records"},
            ),
            _table_widget(
                "incident-profile",
                "Incident profile and document scope",
                ("correlation_id", "title", "severity", "status", "vertical", "duration_seconds"),
                (
                    {
                        "correlation_id": "corr-example",
                        "title": "API latency after rollout",
                        "severity": "critical",
                        "status": "resolved",
                        "vertical": "change_safety",
                        "duration_seconds": 412,
                    },
                ),
            ),
            _table_widget(
                "impact-assessment",
                "Impact assessment",
                ("metric", "baseline", "observed", "threshold", "unit", "impact", "evidence_ref"),
                (
                    {
                        "metric": "API p95 latency",
                        "baseline": 320,
                        "observed": 1840,
                        "threshold": 750,
                        "unit": "ms",
                        "impact": "18% of requests exceeded the latency objective",
                        "evidence_ref": "metric:api.latency.p95",
                    },
                ),
            ),
            _table_widget(
                "event-chronology",
                "Incident chronology",
                (
                    "recorded_at",
                    "phase",
                    "actor",
                    "action_kind",
                    "decision",
                    "outcome",
                    "mode",
                    "summary",
                    "rollback_reference",
                ),
                (
                    {
                        "recorded_at": "2026-07-15T01:00:00Z",
                        "phase": "detection",
                        "actor": "Huginn",
                        "action_kind": "event.ingest",
                        "decision": None,
                        "outcome": "correlated",
                        "mode": "enforce",
                        "summary": "Latency alerts correlated with a deployment event",
                        "rollback_reference": None,
                    },
                    {
                        "recorded_at": "2026-07-15T01:04:00Z",
                        "phase": "recovery",
                        "actor": "Vidar",
                        "action_kind": "config.rollback",
                        "decision": "auto",
                        "outcome": "succeeded",
                        "mode": "enforce",
                        "summary": "Prior configuration revision restored",
                        "rollback_reference": "rbk-01",
                    },
                ),
            ),
            _table_widget(
                "root-cause-hypotheses",
                "Root-cause hypotheses",
                (
                    "tier",
                    "outcome",
                    "cause",
                    "confidence",
                    "reason",
                    "remediation_ref",
                    "mode",
                    "recorded_at",
                ),
                (
                    {
                        "tier": "t1",
                        "outcome": "grounded",
                        "cause": "A connection-limit revision exhausted the API pool",
                        "confidence": 0.82,
                        "reason": (
                            "Change timing and telemetry align with a prior resolved incident"
                        ),
                        "remediation_ref": "config.rollback",
                        "mode": "shadow",
                        "recorded_at": "2026-07-15T01:02:00Z",
                    },
                ),
            ),
            _table_widget(
                "causal-chain",
                "Deterministic causal chain",
                (
                    "hop",
                    "cause_event_id",
                    "cause_resource_ref",
                    "relationship",
                    "effect_event_id",
                    "effect_resource_ref",
                    "lead_seconds",
                    "confidence",
                ),
                (
                    {
                        "hop": 1,
                        "cause_event_id": "change-1",
                        "cause_resource_ref": "database-pool",
                        "relationship": "dependency",
                        "effect_event_id": "failure-1",
                        "effect_resource_ref": "api-service",
                        "lead_seconds": 75,
                        "confidence": 0.82,
                    },
                ),
            ),
            _table_widget(
                "contributing-factors",
                "Contributing factors",
                ("category", "factor", "effect", "confidence", "evidence_ref"),
                (
                    {
                        "category": "capacity",
                        "factor": "No connection headroom alert",
                        "effect": (
                            "The pool reached exhaustion before operators saw a capacity warning"
                        ),
                        "confidence": 0.77,
                        "evidence_ref": "metric:db.pool.available",
                    },
                ),
            ),
            _table_widget(
                "alternative-hypotheses",
                "Alternative hypotheses and exclusion rationale",
                ("hypothesis", "status", "support", "contradiction", "reason", "evidence_refs"),
                (
                    {
                        "hypothesis": "Compute saturation caused latency",
                        "status": "excluded",
                        "support": "CPU rose during the event",
                        "contradiction": "CPU increase followed queue growth",
                        "reason": "Temporal ordering does not support CPU as the initiating cause",
                        "evidence_refs": ["metric:cpu", "event:queue-growth"],
                    },
                ),
            ),
            _table_widget(
                "grounded-citations",
                "Grounded evidence register",
                ("tier", "kind", "ref", "summary", "source_at", "freshness", "recorded_at"),
                (
                    {
                        "tier": "t1",
                        "kind": "change",
                        "ref": "change-1",
                        "summary": "Connection limit changed from 120 to 40",
                        "source_at": "2026-07-15T00:58:45Z",
                        "freshness": "current",
                        "recorded_at": "2026-07-15T01:02:00Z",
                    },
                    {
                        "tier": "t1",
                        "kind": "event",
                        "ref": "<script>alert(1)</script>",
                        "summary": "Escaping regression fixture",
                        "source_at": "2026-07-15T01:00:00Z",
                        "freshness": "current",
                        "recorded_at": "2026-07-15T01:02:00Z",
                    },
                ),
            ),
            _table_widget(
                "response-plan",
                "Response and remediation history",
                (
                    "action_kind",
                    "decision",
                    "outcome",
                    "mode",
                    "rollback_reference",
                    "actor",
                    "recorded_at",
                ),
                (
                    {
                        "action_kind": "config.rollback",
                        "decision": "auto",
                        "outcome": "succeeded",
                        "mode": "enforce",
                        "rollback_reference": "rbk-01",
                        "actor": "Thor",
                        "recorded_at": "2026-07-15T01:04:00Z",
                    },
                ),
            ),
            _table_widget(
                "recovery-validation",
                "Recovery validation",
                ("metric", "before", "after", "target", "status", "evidence_ref"),
                (
                    {
                        "metric": "API p95 latency",
                        "before": "1840 ms",
                        "after": "340 ms",
                        "target": "<= 750 ms",
                        "status": "passed",
                        "evidence_ref": "metric:api.latency.p95",
                    },
                ),
            ),
            _table_widget(
                "control-gaps",
                "Control-gap analysis",
                ("control", "expected", "observed", "gap", "evidence_ref"),
                (
                    {
                        "control": "Connection capacity guard",
                        "expected": "Block revisions below concurrency headroom",
                        "observed": "No pre-deploy pool-capacity check",
                        "gap": "Change safety policy did not model connection demand",
                        "evidence_ref": "rule:connection-capacity",
                    },
                ),
            ),
            _table_widget(
                "recommendations",
                "Corrective and preventive actions",
                (
                    "priority",
                    "action",
                    "owner_role",
                    "due",
                    "verification",
                    "status",
                    "evidence_refs",
                ),
                (
                    {
                        "priority": "P0",
                        "action": "Add deterministic connection-headroom preflight",
                        "owner_role": "Change Safety owner",
                        "due": "2026-07-22",
                        "verification": "Frozen rollout scenario blocks unsafe limits",
                        "status": "proposed",
                        "evidence_refs": ["rule:connection-capacity"],
                    },
                ),
            ),
            _table_widget(
                "limitations",
                "Limitations and unknowns",
                ("limitation", "effect", "next_evidence", "status"),
                (
                    {
                        "limitation": "Client-side retry volume was sampled",
                        "effect": "Exact affected request count is a lower bound",
                        "next_evidence": "Retain full retry telemetry for the next event",
                        "status": "open",
                    },
                ),
            ),
            _table_widget(
                "audit-chronology",
                "Append-only audit chronology",
                ("seq", "event_id", "actor", "action_kind", "mode", "at"),
                (
                    {
                        "seq": 1,
                        "event_id": "event-1",
                        "actor": "Huginn",
                        "action_kind": "event.ingest",
                        "mode": "enforce",
                        "at": "2026-07-15T01:00:00Z",
                    },
                ),
            ),
        ),
        tags=("incident", "rca"),
    )


def _table_widget(
    widget_id: str,
    title: str,
    columns: tuple[str, ...],
    rows: tuple[dict[str, object], ...],
) -> RenderedWidget:
    return RenderedWidget(
        id=widget_id,
        type="table",
        title=title,
        data={"columns": columns, "rows": rows},
    )


def test_render_report_html_builds_dossier_and_escapes_evidence() -> None:
    html = render_report_html(_report())
    assert "Post-Incident Root-Cause Analysis" in html
    assert "At a Glance" in html
    assert "Table of Contents" in html
    assert "Source SHA-256" in html
    assert "corr-example" in html
    assert "Executive Summary" in html
    assert "Alternative Hypotheses" in html
    assert "Corrective and Preventive Actions" in html
    assert "Evidence Completeness" in html
    assert "API p95 latency reached 1840 ms" in html
    assert "<strong>7</strong>" in html
    assert 'class="chronology-table"' in html
    assert 'class="causal-chain-diagram"' in html
    assert 'class="chain-hop"' not in html
    assert 'class="dossier-timeline"' not in html
    assert 'fill="#F4F2F0" stroke="#E3E1DE"' in html
    assert 'fill="#2C333A"' in html
    assert 'class="dossier-section-head"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_encoder_uses_injected_renderer_and_registers_as_pdf() -> None:
    captured: dict[str, str] = {}

    def renderer(html: str, css: str) -> bytes:
        captured["html"] = html
        captured["css"] = css
        return b"%PDF-1.7\nfixture"

    encoder = PdfFormatEncoder(renderer=renderer)
    assert encoder.encode(_report()).startswith(b"%PDF")
    assert "@page" in captured["css"]
    assert "body { margin: 0; background: #fff; }" in captured["css"]
    assert "body { margin: 0; background: #fbfaf9; }" not in captured["css"]
    assert "Incident RCA Dossier" in captured["html"]

    registry = install_pdf_format(FormatRegistry())
    assert registry.get("pdf").content_type == "application/pdf"


def test_weasyprint_renders_real_pdf_when_extra_is_installed() -> None:
    pytest.importorskip("weasyprint")
    rendered = PdfFormatEncoder().encode(_report())
    assert rendered.startswith(b"%PDF")
    assert len(rendered) > 5_000


def test_rca_pdf_layout_guards() -> None:
    weasyprint = pytest.importorskip("weasyprint")
    from fdai.delivery.reporting.pdf_format import _load_css

    document = weasyprint.HTML(string=render_report_html(_report())).render(
        stylesheets=[weasyprint.CSS(string=_load_css())]
    )
    assert 9 <= len(document.pages) <= 11

    chronology_boxes = _layout_boxes(document, "chronology-table", "TableBox")
    assert len(chronology_boxes) == 1
    assert chronology_boxes[0].width >= 600
    assert chronology_boxes[0].height >= 100

    causal_boxes = _layout_boxes(document, "causal-chain-diagram")
    assert len(causal_boxes) == 1
    assert causal_boxes[0].width >= 600
    assert causal_boxes[0].height >= 100

    section_headers = _layout_boxes(document, "dossier-section-head")
    assert len(section_headers) == 13
    assert all(box.width >= 600 and box.height >= 50 for box in section_headers)


def _layout_boxes(document: object, class_name: str, box_type: str | None = None) -> list[object]:
    found: list[object] = []

    def visit(box: object) -> None:
        element = getattr(box, "element", None)
        classes = element.get("class", "").split() if element is not None else []
        if class_name in classes and (box_type is None or type(box).__name__ == box_type):
            found.append(box)
        for child in getattr(box, "children", ()):
            visit(child)

    for page in document.pages:
        visit(page._page_box)  # noqa: SLF001 - intentional print-layout regression seam
    return found
