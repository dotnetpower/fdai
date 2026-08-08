"""Bounded native-text PDF extraction and OCR citation normalization."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable

from pypdf import PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import ArrayObject, StreamObject

from fdai.shared.contracts import StructuralUnit
from fdai.shared.providers.local.document_limits import (
    DEFAULT_DOCUMENT_PARSER_POLICY,
    DocumentParserPolicy,
)

_BLOCK_BREAK = re.compile(r"\n\s*\n+")


class _PdfPolicyError(ValueError):
    pass


def extract_pdf_text(
    content: bytes,
    *,
    policy: DocumentParserPolicy = DEFAULT_DOCUMENT_PARSER_POLICY,
) -> tuple[StructuralUnit, ...]:
    """Extract native text blocks with strict pypdf parsing and bounded output."""
    if len(content) > policy.max_input_bytes:
        raise _PdfPolicyError("PDF bytes exceed the parser budget")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise _PdfPolicyError("encrypted PDF extraction is not supported")
        page_count = len(reader.pages)
        if page_count < 1 or page_count > policy.max_pdf_pages:
            raise _PdfPolicyError("PDF page count is outside the parser budget")
        if _pdf_object_count(reader) > policy.max_pdf_objects:
            raise _PdfPolicyError("PDF object count exceeds the parser budget")

        units: list[StructuralUnit] = []
        total_characters = 0
        raw_stream_bytes = 0
        decoded_stream_bytes = 0
        for page_number, page in enumerate(reader.pages, start=1):
            raw_bytes, decoded_bytes = _page_content_stream_bytes(page)
            raw_stream_bytes += raw_bytes
            decoded_stream_bytes += decoded_bytes
            if raw_stream_bytes > policy.max_pdf_raw_stream_bytes:
                raise _PdfPolicyError("PDF raw content stream exceeds the parser budget")
            if decoded_stream_bytes > policy.max_pdf_decoded_stream_bytes:
                raise _PdfPolicyError("PDF decoded content stream exceeds the parser budget")
            blocks = _page_text_blocks(page.extract_text())
            for block_number, block_text in enumerate(blocks, start=1):
                total_characters += len(block_text)
                if (
                    len(units) >= policy.max_pdf_units
                    or total_characters > policy.max_pdf_characters
                ):
                    raise _PdfPolicyError("PDF extracted text exceeds the parser budget")
                units.append(
                    StructuralUnit(
                        unit_id=f"pdf-page-{page_number}-block-{block_number}",
                        kind="page",
                        locator=f"pdf/page:{page_number}/block:{block_number}",
                        text=block_text,
                    )
                )
        return tuple(units)
    except _PdfPolicyError as exc:
        raise ValueError(str(exc)) from None
    except (
        PyPdfError,
        AttributeError,
        MemoryError,
        OSError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        raise ValueError("PDF parsing or text extraction failed") from None


def _pdf_object_count(reader: PdfReader) -> int:
    object_ids = {
        object_id for generation_entries in reader.xref.values() for object_id in generation_entries
    }
    object_ids.update(reader.xref_objStm)
    return len(object_ids)


def _page_content_stream_bytes(page: object) -> tuple[int, int]:
    contents = page.get("/Contents")  # type: ignore[attr-defined]
    if contents is None:
        return 0, 0
    resolved = contents.get_object()
    values = resolved if isinstance(resolved, ArrayObject) else (resolved,)
    streams = tuple(item.get_object() for item in values)
    if any(not isinstance(stream, StreamObject) for stream in streams):
        raise _PdfPolicyError("PDF content stream is malformed")
    raw_bytes = sum(len(stream._data) for stream in streams)  # noqa: SLF001
    decoded_bytes = sum(len(stream.get_data()) for stream in streams)
    return raw_bytes, decoded_bytes


def _page_text_blocks(text: str) -> tuple[str, ...]:
    return tuple(
        normalized for block in _BLOCK_BREAK.split(text) if (normalized := " ".join(block.split()))
    )


def normalize_pdf_ocr_units(
    units: Iterable[StructuralUnit],
    *,
    policy: DocumentParserPolicy = DEFAULT_DOCUMENT_PARSER_POLICY,
) -> tuple[StructuralUnit, ...]:
    """Validate OCR page citations and convert them to canonical PDF locators."""
    normalized: list[StructuralUnit] = []
    seen_unit_ids: set[str] = set()
    seen_locators: set[str] = set()
    previous_position = (0, 0)
    total_characters = 0
    for unit in units:
        if unit.unit_id in seen_unit_ids or unit.locator in seen_locators:
            raise ValueError("PDF OCR units MUST have unique identities and locators")
        seen_unit_ids.add(unit.unit_id)
        seen_locators.add(unit.locator)
        page_number, block_number = _ocr_position(unit.locator)
        if page_number > policy.max_ocr_pages:
            raise ValueError("PDF OCR page count exceeds the parser budget")
        if (page_number, block_number) <= previous_position:
            raise ValueError("PDF OCR units MUST be ordered by page and block")
        previous_position = (page_number, block_number)
        text = " ".join(unit.text.split())
        if not text:
            continue
        total_characters += len(text)
        if len(normalized) >= policy.max_ocr_units or total_characters > policy.max_ocr_characters:
            raise ValueError("PDF OCR output exceeds the parser budget")
        normalized.append(
            StructuralUnit(
                unit_id=f"pdf-page-{page_number}-ocr-{block_number}",
                kind="page",
                locator=f"pdf/page:{page_number}/ocr:{block_number}",
                text=text,
            )
        )
    if not normalized:
        raise ValueError("PDF OCR returned no cited text")
    return tuple(normalized)


def _ocr_position(locator: str) -> tuple[int, int]:
    match = re.fullmatch(
        r"(?:pdf/)?page:(\d+)(?:/(?:ocr|block):(\d+)|:line:(\d+))",
        locator,
    )
    if match is None or int(match.group(1)) < 1:
        raise ValueError("PDF OCR unit locator MUST identify a positive page and block")
    block_number = int(match.group(2) or match.group(3) or 0)
    if block_number < 1:
        raise ValueError("PDF OCR unit locator MUST identify a positive page and block")
    return int(match.group(1)), block_number


__all__ = ["extract_pdf_text", "normalize_pdf_ocr_units"]
