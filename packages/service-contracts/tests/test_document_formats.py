from __future__ import annotations

import pytest

from fdai_service_contracts import (
    classify_document_intake,
    supported_document_extensions,
    supported_document_format_ids,
)


@pytest.mark.parametrize(
    ("source_name", "media_type", "format_id", "family"),
    [
        ("guide.md", "text/markdown", "text", "text"),
        ("report.PDF", "application/pdf", "pdf", "pdf"),
        (
            "runbook.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
            "ooxml",
        ),
        ("slides.pptx", "application/octet-stream", "pptx", "ooxml"),
        ("data.xlsx", "application/zip", "xlsx", "ooxml"),
        ("scan.tiff", "image/tiff", "tiff", "image"),
    ],
)
def test_classifies_supported_document_hints(
    source_name: str,
    media_type: str,
    format_id: str,
    family: str,
) -> None:
    spec = classify_document_intake(source_name, media_type)
    assert (spec.format_id, spec.family) == (format_id, family)


@pytest.mark.parametrize("source_name", ["report.doc", "slides.ppt", "budget.xls"])
def test_rejects_legacy_office_with_conversion_guidance(source_name: str) -> None:
    with pytest.raises(ValueError, match="legacy Office format"):
        classify_document_intake(source_name, "application/octet-stream")


def test_rejects_unknown_extensions_and_specific_media_mismatches() -> None:
    with pytest.raises(ValueError, match="unsupported document format"):
        classify_document_intake("archive.zip", "application/zip")
    with pytest.raises(ValueError, match="does not match"):
        classify_document_intake("report.pdf", "image/png")


def test_capability_ids_and_extensions_are_unique() -> None:
    ids = supported_document_format_ids()
    without_ocr = supported_document_format_ids(include_ocr=False)
    extensions = supported_document_extensions()
    assert ids == ("text", "pdf", "docx", "pptx", "xlsx", "png", "jpeg", "tiff")
    assert without_ocr == ("text", "pdf", "docx", "pptx", "xlsx")
    assert len(extensions) == len(set(extensions))
