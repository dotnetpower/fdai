"""Pure bounded parsing helpers for document extraction."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from fdai_service_contracts import (
    DocumentExtractionUnavailableError,
    ExtractionUnavailableReason,
    ProtectionInspection,
    ProtectionState,
    StructuralUnit,
)

from fdai_document_worker_service.adapters.pdf_isolation import inspect_pdf_pages_isolated


async def _read_bounded(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    content = bytearray()
    async for chunk in chunks:
        content.extend(chunk)
        if len(content) > limit:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.INPUT_BUDGET)
    return bytes(content)


def _text_units(text: str) -> tuple[StructuralUnit, ...]:
    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", text) if value.strip()]
    return tuple(
        StructuralUnit(
            unit_id=f"text-{index}", kind="paragraph", locator=f"paragraph:{index}", text=value
        )
        for index, value in enumerate(paragraphs, start=1)
    )


def _pdf_inspection(
    content: bytes,
) -> tuple[tuple[StructuralUnit | None, ...], tuple[bool, ...]]:
    """Preserve page text and image-presence facts from the isolated parser."""
    pages = inspect_pdf_pages_isolated(content)
    units = tuple(
        StructuralUnit(
            unit_id=f"page-{index}",
            kind="page",
            locator=f"pdf/page:{index}/block:1",
            text=page.text,
        )
        if page.text is not None
        else None
        for index, page in enumerate(pages, start=1)
    )
    return units, tuple(page.has_images for page in pages)


def _normalize_pdf_ocr_units(units: Sequence[StructuralUnit]) -> tuple[StructuralUnit, ...]:
    """Validate ordered provider citations and emit canonical PDF OCR locators."""
    normalized: list[StructuralUnit] = []
    seen_unit_ids: set[str] = set()
    seen_locators: set[str] = set()
    previous_position = (0, 0)
    for unit in units:
        if unit.unit_id in seen_unit_ids or unit.locator in seen_locators:
            raise ValueError("PDF OCR units MUST have unique identities and locators")
        seen_unit_ids.add(unit.unit_id)
        seen_locators.add(unit.locator)
        page_number, block_number = _pdf_ocr_position(unit.locator)
        if (page_number, block_number) <= previous_position:
            raise ValueError("PDF OCR units MUST be ordered by page and block")
        previous_position = (page_number, block_number)
        text = " ".join(unit.text.split())
        if not text:
            continue
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


def _merge_pdf_units(
    pdf_pages: Sequence[StructuralUnit | None],
    ocr_units: Sequence[StructuralUnit],
) -> tuple[StructuralUnit, ...]:
    """Merge page OCR without duplicating exact native page text."""
    ocr_by_page: dict[int, list[StructuralUnit]] = {}
    for unit in ocr_units:
        page_number, _ = _pdf_ocr_position(unit.locator)
        if page_number > len(pdf_pages):
            raise ValueError("PDF OCR cited a page outside the source document")
        ocr_by_page.setdefault(page_number, []).append(unit)

    merged: list[StructuralUnit] = []
    for page_number, native_unit in enumerate(pdf_pages, start=1):
        if native_unit is not None:
            merged.append(native_unit)
            native_text = " ".join(native_unit.text.split()).casefold()
            merged.extend(
                unit
                for unit in ocr_by_page.get(page_number, ())
                if (ocr_text := " ".join(unit.text.split()).casefold())
                and ocr_text not in native_text
                and native_text not in ocr_text
            )
        else:
            page_ocr = ocr_by_page.get(page_number)
            if not page_ocr:
                raise ValueError(f"PDF OCR returned no cited text for page {page_number}")
            merged.extend(page_ocr)
    return tuple(merged)


def _pdf_ocr_position(locator: str) -> tuple[int, int]:
    """Decode a positive provider page/block citation without trusting its prefix."""
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


def _ocr_units(
    payload: dict[str, object], max_lines: int, max_chars: int
) -> tuple[StructuralUnit, ...]:
    result = payload.get("analyzeResult")
    pages = result.get("pages") if isinstance(result, dict) else None
    if not isinstance(pages, list):
        raise RuntimeError("OCR result has no pages")
    units: list[StructuralUnit] = []
    characters = 0
    for page_index, page in enumerate(pages, start=1):
        lines = page.get("lines") if isinstance(page, dict) else None
        if not isinstance(lines, list):
            raise RuntimeError("OCR page has no lines")
        for line_index, line in enumerate(lines, start=1):
            text = line.get("content") if isinstance(line, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            characters += len(text)
            if len(units) >= max_lines or characters > max_chars:
                raise RuntimeError("OCR output exceeded configured bounds")
            units.append(
                StructuralUnit(
                    unit_id=f"page-{page_index}-line-{line_index}",
                    kind="page",
                    locator=f"page:{page_index}:line:{line_index}",
                    text=text.strip(),
                )
            )
    return tuple(units)


def _looks_like_text(content: bytes) -> bool:
    sample = content[:4096]
    return b"\0" not in sample and (
        not sample
        or sum(value < 32 and value not in (9, 10, 13) for value in sample) / len(sample) < 0.02
    )


def _image_media_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def _ooxml_package_format(names: set[str]) -> str | None:
    if "word/document.xml" in names:
        return "docx"
    if "ppt/presentation.xml" in names or any(
        name.startswith("ppt/slides/slide") and name.endswith(".xml") for name in names
    ):
        return "pptx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    return None


def _format_mismatch() -> ProtectionInspection:
    return ProtectionInspection(
        ProtectionState.UNKNOWN,
        "format-signature-mismatch",
        "application/octet-stream",
        reason_code="format_signature_mismatch",
    )


def _embedded_image_units(
    units: Sequence[StructuralUnit],
    *,
    image_number: int,
) -> tuple[StructuralUnit, ...]:
    normalized: list[StructuralUnit] = []
    for line_number, unit in enumerate(units, start=1):
        text = " ".join(unit.text.split())
        if not text:
            continue
        normalized.append(
            StructuralUnit(
                unit_id=f"embedded-image-{image_number}-line-{line_number}",
                kind="page",
                locator=f"ooxml/embedded-image:{image_number}/ocr:{line_number}",
                text=text,
            )
        )
    return tuple(normalized)
