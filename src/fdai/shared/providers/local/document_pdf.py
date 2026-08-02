"""Bounded native-text PDF extraction and OCR citation normalization."""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable

from fdai.shared.contracts import StructuralUnit

_MAX_EXPANDED_BYTES = 64 * 1024 * 1024
_MAX_PDF_OBJECTS = 10_000
_MAX_PDF_PAGES = 1_000
_MAX_PDF_PAGE_TREE_DEPTH = 128
_MAX_UNITS = 20_000
_MAX_CHARACTERS = 2_000_000
_PDF_OBJECT = re.compile(rb"(?ms)(\d+)\s+(\d+)\s+obj\b(.*?)endobj")
_PDF_REF = re.compile(rb"(\d+)\s+(\d+)\s+R")
_PDF_TYPE = re.compile(rb"/Type\s*/([A-Za-z]+)")
_PDF_PAGES_REF = re.compile(rb"/Pages\s+(\d+)\s+(\d+)\s+R")
_PDF_KIDS = re.compile(rb"(?s)/Kids\s*\[(.*?)\]")
_PDF_CONTENTS = re.compile(rb"(?s)/Contents\s*(\[.*?\]|\d+\s+\d+\s+R)")
_PDF_TEXT_BLOCK = re.compile(rb"(?s)BT\b(.*?)ET\b")
_PDF_STREAM = re.compile(rb"(?<!\S)stream(?:\r\n|\r|\n)")


def extract_pdf_text(content: bytes) -> tuple[StructuralUnit, ...]:
    """Extract native text blocks in page-tree order from a bounded PDF."""
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]:
        raise ValueError("PDF structure is incomplete")
    objects = {
        (int(match.group(1)), int(match.group(2))): match.group(3)
        for match in _PDF_OBJECT.finditer(content)
    }
    if not objects or len(objects) > _MAX_PDF_OBJECTS:
        raise ValueError("PDF object count is outside the parser budget")
    catalog = next(
        (body for body in objects.values() if _object_type(body) == b"Catalog"),
        None,
    )
    if catalog is None or (pages_match := _PDF_PAGES_REF.search(catalog)) is None:
        raise ValueError("PDF page tree is missing")
    root_ref = (int(pages_match.group(1)), int(pages_match.group(2)))
    page_refs = _pdf_page_refs(objects, root_ref)
    if not page_refs or len(page_refs) > _MAX_PDF_PAGES:
        raise ValueError("PDF page count is outside the parser budget")

    units: list[StructuralUnit] = []
    total_characters = 0
    for page_number, page_ref in enumerate(page_refs, start=1):
        page = objects[page_ref]
        for block_number, block_text in enumerate(_page_text_blocks(page, objects), start=1):
            total_characters += len(block_text)
            if len(units) >= _MAX_UNITS or total_characters > _MAX_CHARACTERS:
                raise ValueError("PDF extracted text exceeds the parser budget")
            units.append(
                StructuralUnit(
                    unit_id=f"pdf-page-{page_number}-block-{block_number}",
                    kind="page",
                    locator=f"pdf/page:{page_number}/block:{block_number}",
                    text=block_text,
                )
            )
    return tuple(units)


def normalize_pdf_ocr_units(units: Iterable[StructuralUnit]) -> tuple[StructuralUnit, ...]:
    """Validate OCR page citations and convert them to canonical PDF locators."""
    normalized: list[StructuralUnit] = []
    per_page: dict[int, int] = {}
    seen_unit_ids: set[str] = set()
    seen_locators: set[str] = set()
    previous_page = 0
    total_characters = 0
    for unit in units:
        if unit.unit_id in seen_unit_ids or unit.locator in seen_locators:
            raise ValueError("PDF OCR units MUST have unique identities and locators")
        seen_unit_ids.add(unit.unit_id)
        seen_locators.add(unit.locator)
        page_number = _ocr_page_number(unit.locator)
        if page_number < previous_page:
            raise ValueError("PDF OCR units MUST be ordered by page")
        previous_page = page_number
        text = " ".join(unit.text.split())
        if not text:
            continue
        per_page[page_number] = per_page.get(page_number, 0) + 1
        block_number = per_page[page_number]
        total_characters += len(text)
        if len(normalized) >= _MAX_UNITS or total_characters > _MAX_CHARACTERS:
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


def _pdf_page_refs(
    objects: dict[tuple[int, int], bytes], root_ref: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    pages: list[tuple[int, int]] = []
    visiting: set[tuple[int, int]] = set()

    def visit(reference: tuple[int, int], depth: int) -> None:
        if depth > _MAX_PDF_PAGE_TREE_DEPTH:
            raise ValueError("PDF page tree exceeds the parser depth budget")
        if reference in visiting:
            raise ValueError("PDF page tree contains a cycle")
        body = objects.get(reference)
        if body is None:
            raise ValueError("PDF page tree references a missing object")
        object_type = _object_type(body)
        if object_type == b"Page":
            pages.append(reference)
            return
        if object_type != b"Pages" or (kids := _PDF_KIDS.search(body)) is None:
            raise ValueError("PDF page tree node is malformed")
        visiting.add(reference)
        for match in _PDF_REF.finditer(kids.group(1)):
            visit((int(match.group(1)), int(match.group(2))), depth + 1)
        visiting.remove(reference)

    visit(root_ref, 1)
    return tuple(pages)


def _page_text_blocks(page: bytes, objects: dict[tuple[int, int], bytes]) -> tuple[str, ...]:
    contents = _PDF_CONTENTS.search(page)
    if contents is None:
        return ()
    blocks: list[str] = []
    for match in _PDF_REF.finditer(contents.group(1)):
        stream_object = objects.get((int(match.group(1)), int(match.group(2))))
        if stream_object is None:
            raise ValueError("PDF content stream reference is missing")
        stream = _pdf_stream(stream_object)
        for text_block in _PDF_TEXT_BLOCK.findall(stream):
            text = " ".join(_pdf_text_fragments(text_block)).strip()
            if text:
                blocks.append(text)
    return tuple(blocks)


def _pdf_stream(body: bytes) -> bytes:
    marker = _PDF_STREAM.search(body)
    if marker is None or (end := body.find(b"endstream", marker.end())) < 0:
        raise ValueError("PDF content stream is malformed")
    stream = body[marker.end() : end].rstrip(b"\r\n")
    if b"/Filter" not in body[: marker.start()]:
        return stream
    if re.search(rb"/Filter\s*/FlateDecode\b", body[: marker.start()]):
        try:
            decoded = zlib.decompress(stream)
        except zlib.error as exc:
            raise ValueError("PDF Flate stream is corrupt") from exc
        if len(decoded) > _MAX_EXPANDED_BYTES:
            raise ValueError("PDF stream expansion exceeds the parser budget")
        return decoded
    raise ValueError("PDF content stream uses an unsupported filter")


def _pdf_text_fragments(block: bytes) -> tuple[str, ...]:
    fragments: list[str] = []
    index = 0
    while index < len(block):
        if block[index] == 0x28:
            raw, index = _pdf_literal(block, index + 1)
            fragments.append(_decode_pdf_text(raw))
        elif block[index] == 0x3C and index + 1 < len(block) and block[index + 1] != 0x3C:
            end = block.find(b">", index + 1)
            if end < 0:
                raise ValueError("PDF hexadecimal string is incomplete")
            compact = re.sub(rb"\s+", b"", block[index + 1 : end])
            if len(compact) % 2:
                compact += b"0"
            try:
                fragments.append(_decode_pdf_text(bytes.fromhex(compact.decode("ascii"))))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError("PDF hexadecimal string is invalid") from exc
            index = end + 1
        else:
            index += 1
    return tuple(fragment for fragment in fragments if fragment)


def _pdf_literal(block: bytes, index: int) -> tuple[bytes, int]:
    output = bytearray()
    depth = 1
    while index < len(block):
        value = block[index]
        if value == 0x5C:
            index += 1
            if index >= len(block):
                break
            escaped = block[index]
            replacements = {
                ord("n"): 10,
                ord("r"): 13,
                ord("t"): 9,
                ord("b"): 8,
                ord("f"): 12,
            }
            if escaped in replacements:
                output.append(replacements[escaped])
            elif 48 <= escaped <= 55:
                digits = bytes([escaped])
                while len(digits) < 3 and index + 1 < len(block) and 48 <= block[index + 1] <= 55:
                    index += 1
                    digits += bytes([block[index]])
                output.append(int(digits, 8))
            elif escaped not in (10, 13):
                output.append(escaped)
        elif value == 0x28:
            depth += 1
            output.append(value)
        elif value == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(output), index + 1
            output.append(value)
        else:
            output.append(value)
        index += 1
    raise ValueError("PDF literal string is incomplete")


def _decode_pdf_text(value: bytes) -> str:
    if value.startswith(b"\xfe\xff"):
        try:
            return value[2:].decode("utf-16-be").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("PDF UTF-16 text is invalid") from exc
    if any(byte < 32 or byte > 126 for byte in value):
        raise ValueError("PDF text requires an unsupported font character map")
    return value.decode("ascii").strip()


def _object_type(body: bytes) -> bytes | None:
    marker = _PDF_STREAM.search(body)
    match = _PDF_TYPE.search(body if marker is None else body[: marker.start()])
    return match.group(1) if match is not None else None


def _ocr_page_number(locator: str) -> int:
    match = re.fullmatch(
        r"(?:pdf/)?page:(\d+)(?:/(?:ocr|block):(\d+)|:line:(\d+))",
        locator,
    )
    if match is None or int(match.group(1)) < 1:
        raise ValueError("PDF OCR unit locator MUST identify a positive page and block")
    return int(match.group(1))


__all__ = ["extract_pdf_text", "normalize_pdf_ocr_units"]
