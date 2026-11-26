"""Optional report delivery adapters owned by the independent Operator Service."""

from __future__ import annotations

from fdai_operator_service.families.operations import ReportPdfEncoder


def optional_pdf_report_encoder() -> ReportPdfEncoder | None:
    """Return the PDF adapter only when the package extra is importable."""
    try:
        from fdai_operator_service.reporting.pdf_format import PdfReportEncoder
    except ModuleNotFoundError as exc:
        if exc.name == "weasyprint":
            return None
        raise
    return PdfReportEncoder()


__all__ = ["optional_pdf_report_encoder"]
