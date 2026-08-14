"""Focused regression tests for optional materialized-report PDF delivery."""

from __future__ import annotations

import io
from collections.abc import Mapping

import fdai_operator_service.reporting.pdf_format as pdf_format_module
import pytest
from fdai_operator_service.families.operations import ReportPdfEncodingError
from fdai_operator_service.reporting.pdf_format import (
    MAX_WIDGETS,
    PdfReportEncoder,
    source_envelope_digest,
)
from pypdf import PdfReader


def _report(*, widgets: tuple[Mapping[str, object], ...] | None = None) -> dict[str, object]:
    return {
        "id": "incident-rca-dossier",
        "version": "1.0.0",
        "name": "Incident <RCA> Dossier",
        "description": "Recorded evidence only: <script>alert(1)</script>",
        "generated_at": "2026-08-14T00:00:00+00:00",
        "time_range": {
            "since": "2026-08-13T00:00:00+00:00",
            "until": "2026-08-14T00:00:00+00:00",
        },
        "variables": {"correlation_id": "corr-example"},
        "widgets": list(
            widgets
            or (
                {
                    "id": "incident-profile",
                    "type": "table",
                    "title": "Incident profile",
                    "data": {
                        "columns": ["field", "value"],
                        "rows": [{"field": "signal", "value": "CPU > 90%"}],
                    },
                    "options": {},
                },
                {
                    "id": "root-cause",
                    "type": "table",
                    "title": "Root-cause hypotheses",
                    "data": {"columns": [], "rows": []},
                    "options": {},
                    "error": "authoritative hypothesis evidence is unavailable",
                },
                {
                    "id": "limitations",
                    "type": "table",
                    "title": "Limitations and unknowns",
                    "data": {"items": ["No independent causal evidence was recorded."]},
                    "options": {},
                },
            )
        ),
        "tags": ["incident", "rca"],
        "provenance": {
            "availability": "partial",
            "synthetic": False,
            "sources": [
                {
                    "datasource": "audit",
                    "source": "postgres",
                    "availability": "available",
                    "synthetic": False,
                    "as_of": "2026-08-14T00:00:00+00:00",
                }
            ],
        },
    }


def _pdf_text(payload: bytes) -> tuple[int, str]:
    reader = PdfReader(io.BytesIO(payload))
    return len(reader.pages), "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_preserves_recorded_values_gaps_digest_and_pagination() -> None:
    report = _report()

    payload = PdfReportEncoder().encode(report)
    page_count, text = _pdf_text(payload)

    assert page_count >= 3
    assert "Incident <RCA> Dossier" in text
    assert "<script>alert(1)</script>" in text
    assert "Unavailable section" in text
    assert "authoritative hypothesis evidence is unavailable" in text
    assert "No independent causal evidence was recorded." in text
    assert f"sha256:{source_envelope_digest(report)}" in text.replace("\n", "")
    assert "Root cause confirmed" not in text
    assert "Recommended remediation" not in text


def test_source_digest_is_stable_across_mapping_order() -> None:
    report = _report()
    reordered = dict(reversed(tuple(report.items())))

    assert source_envelope_digest(report) == source_envelope_digest(reordered)


def test_pdf_fails_closed_if_generated_markup_references_external_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pdf_format_module,
        "_report_html",
        lambda report, *, digest: "<img src='https://example.invalid/private'>",
    )

    with pytest.raises(ReportPdfEncodingError, match="external resources"):
        PdfReportEncoder().encode(_report())


@pytest.mark.parametrize(
    "report",
    [
        {**_report(), "name": ""},
        {**_report(), "widgets": "not-an-array"},
        {**_report(), "widgets": [{}] * (MAX_WIDGETS + 1)},
        {**_report(), "provenance": {"value": float("nan")}},
    ],
)
def test_pdf_rejects_malformed_or_unbounded_envelopes(report: Mapping[str, object]) -> None:
    with pytest.raises(ReportPdfEncodingError):
        PdfReportEncoder().encode(report)
