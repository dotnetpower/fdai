"""Adversarial tests for bounded document structure extraction."""

from __future__ import annotations

import io
import zipfile
import zlib

import pytest

from fdai.shared.contracts import StructuralUnit
from fdai.shared.providers.local import document_pdf, document_structure
from fdai.shared.providers.local.document_structure import (
    extract_ooxml,
    extract_pdf_text,
    normalize_pdf_ocr_units,
)


def test_docx_preserves_numeric_unit_across_run_boundaries() -> None:
    xml = (
        b"<w:document xmlns:w='urn:w'><w:body><w:p>"
        b"<w:r><w:t>Latency must stay below 250</w:t></w:r>"
        b"<w:r><w:t xml:space='preserve'> ms.</w:t></w:r>"
        b"</w:p></w:body></w:document>"
    )

    units = extract_ooxml(_ooxml({"word/document.xml": xml}))

    assert units[0].text == "Latency must stay below 250 ms."


def test_docx_locators_preserve_empty_paragraph_ordinals() -> None:
    xml = (
        b"<w:document xmlns:w='urn:w'><w:body>"
        b"<w:p/><w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>"
        b"<w:p><w:pPr><w:pStyle w:val='Heading2'/></w:pPr></w:p>"
        b"<w:p><w:pPr><w:pStyle w:val='Heading2'/></w:pPr>"
        b"<w:r><w:t>Second heading</w:t></w:r></w:p>"
        b"</w:body></w:document>"
    )

    units = extract_ooxml(_ooxml({"word/document.xml": xml}))

    assert [unit.unit_id for unit in units] == ["docx-paragraph-2", "docx-paragraph-4"]
    assert [unit.locator for unit in units] == ["docx/paragraph:2", "docx/heading:2:2"]


def test_pptx_extracts_every_table_within_one_shape() -> None:
    table = (
        b"<a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
        b"</a:txBody></a:tc></a:tr></a:tbl>"
    )
    slide = (
        b"<p:sld xmlns:p='urn:p' xmlns:a='urn:a'><p:cSld><p:spTree>"
        b"<p:graphicFrame><a:graphic><a:graphicData>"
        + table.replace(b"{text}", b"first")
        + table.replace(b"{text}", b"second")
        + b"</a:graphicData></a:graphic></p:graphicFrame>"
        b"</p:spTree></p:cSld></p:sld>"
    )

    units = extract_ooxml(_ooxml({"ppt/slides/slide1.xml": slide}))

    assert [unit.text for unit in units] == ["first", "second"]
    assert [unit.locator for unit in units] == [
        "pptx/slide:1/shape:1/table:1/row:1/cell:1",
        "pptx/slide:1/shape:1/table:2/row:1/cell:1",
    ]


def test_pdf_rejects_unproven_font_mapping_and_deep_page_tree() -> None:
    with pytest.raises(ValueError, match="font character map"):
        extract_pdf_text(_pdf(stream=b"BT (\x80) Tj ET"))

    with pytest.raises(ValueError, match="depth budget"):
        extract_pdf_text(_deep_pdf(depth=130))


def test_pdf_ocr_rejects_duplicate_or_reordered_citations() -> None:
    duplicate = (
        StructuralUnit(unit_id="unit-1", kind="page", locator="page:1:line:1", text="first"),
        StructuralUnit(unit_id="unit-2", kind="page", locator="page:1:line:1", text="second"),
    )
    with pytest.raises(ValueError, match="unique"):
        normalize_pdf_ocr_units(duplicate)

    reordered = (
        StructuralUnit(unit_id="unit-2", kind="page", locator="page:2:line:1", text="second"),
        StructuralUnit(unit_id="unit-1", kind="page", locator="page:1:line:1", text="first"),
    )
    with pytest.raises(ValueError, match="ordered by page"):
        normalize_pdf_ocr_units(reordered)


def test_pdf_ocr_validates_locator_empty_output_and_budget(monkeypatch) -> None:
    valid = (
        StructuralUnit(unit_id="unit-1", kind="page", locator="pdf/page:2/ocr:7", text="  text  "),
    )
    assert normalize_pdf_ocr_units(valid)[0].locator == "pdf/page:2/ocr:1"
    with pytest.raises(ValueError, match="positive page"):
        normalize_pdf_ocr_units(
            (StructuralUnit(unit_id="bad", kind="page", locator="page:0:line:1", text="x"),)
        )
    with pytest.raises(ValueError, match="no cited text"):
        normalize_pdf_ocr_units(
            (StructuralUnit(unit_id="empty", kind="page", locator="page:1:line:1", text=" "),)
        )
    monkeypatch.setattr(document_pdf, "_MAX_CHARACTERS", 1)
    with pytest.raises(ValueError, match="parser budget"):
        normalize_pdf_ocr_units(valid)


def test_pdf_stream_filter_and_expansion_guards(monkeypatch) -> None:
    assert document_pdf._pdf_stream(b"<<>> stream\nraw\nendstream") == b"raw"
    assert document_pdf._pdf_stream(b"<<>>\rstream\rraw\rendstream") == b"raw"
    assert document_pdf._object_type(b"<< /Label (stream error) /Type /Page >>") == b"Page"
    compressed = zlib.compress(b"decoded")
    flate = b"<< /Filter /FlateDecode >> stream\n" + compressed + b"\nendstream"
    assert document_pdf._pdf_stream(flate) == b"decoded"
    with pytest.raises(ValueError, match="unsupported filter"):
        document_pdf._pdf_stream(b"<< /Filter /ASCII85Decode >> stream\nx\nendstream")
    with pytest.raises(ValueError, match="corrupt"):
        document_pdf._pdf_stream(b"<< /Filter /FlateDecode >> stream\nbad\nendstream")
    with pytest.raises(ValueError, match="malformed"):
        document_pdf._pdf_stream(b"<<>>")
    monkeypatch.setattr(document_pdf, "_MAX_EXPANDED_BYTES", 1)
    with pytest.raises(ValueError, match="expansion"):
        document_pdf._pdf_stream(flate)


def test_pdf_string_decoding_is_bounded_and_explicit() -> None:
    assert document_pdf._pdf_text_fragments(b"<4869> Tj") == ("Hi",)
    assert document_pdf._pdf_text_fragments(b"(a\\050b\\051) Tj") == ("a(b)",)
    assert document_pdf._decode_pdf_text(b"\xfe\xff\x00H\x00i") == "Hi"
    with pytest.raises(ValueError, match="incomplete"):
        document_pdf._pdf_text_fragments(b"<48")
    with pytest.raises(ValueError, match="invalid"):
        document_pdf._pdf_text_fragments(b"<zz>")
    with pytest.raises(ValueError, match="incomplete"):
        document_pdf._pdf_text_fragments(b"(open")
    with pytest.raises(ValueError, match="UTF-16"):
        document_pdf._decode_pdf_text(b"\xfe\xff\x00")


def test_pdf_page_tree_and_document_shape_fail_closed(monkeypatch) -> None:
    page = b"<< /Type /Page >>"
    assert document_pdf._pdf_page_refs(
        {(1, 0): b"<< /Type /Pages /Kids [2 0 R] >>", (2, 0): page},
        (1, 0),
    ) == ((2, 0),)
    with pytest.raises(ValueError, match="missing object"):
        document_pdf._pdf_page_refs({(1, 0): b"<< /Type /Pages /Kids [2 0 R] >>"}, (1, 0))
    with pytest.raises(ValueError, match="cycle"):
        document_pdf._pdf_page_refs(
            {(1, 0): b"<< /Type /Pages /Kids [1 0 R] >>"},
            (1, 0),
        )
    with pytest.raises(ValueError, match="malformed"):
        document_pdf._pdf_page_refs({(1, 0): b"<< /Type /Other >>"}, (1, 0))
    with pytest.raises(ValueError, match="incomplete"):
        extract_pdf_text(b"not-pdf")
    with pytest.raises(ValueError, match="object count"):
        extract_pdf_text(b"%PDF-1.7\n%%EOF")
    with pytest.raises(ValueError, match="page tree is missing"):
        extract_pdf_text(b"%PDF-1.7\n1 0 obj << /Type /Other >> endobj\n%%EOF")
    monkeypatch.setattr(document_pdf, "_MAX_PDF_PAGES", 0)
    with pytest.raises(ValueError, match="page count"):
        extract_pdf_text(_pdf(stream=b"BT (text) Tj ET"))


def test_ooxml_rejects_unsafe_members_and_declarations(monkeypatch) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../escape", "x")
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        with pytest.raises(ValueError, match="unsafe member"):
            document_structure.validated_zip_members(archive)

    monkeypatch.setattr(document_structure, "_MAX_ZIP_MEMBERS", 0)
    with zipfile.ZipFile(io.BytesIO(_ooxml({}))) as archive:
        with pytest.raises(ValueError, match="member count"):
            document_structure.validated_zip_members(archive)
    with pytest.raises(ValueError, match="prohibited declaration"):
        document_structure._xml_root(b"<!DOCTYPE x><x/>")


def test_ooxml_missing_structure_and_sheet_fallback() -> None:
    with pytest.raises(ValueError, match="body is missing"):
        extract_ooxml(_ooxml({"word/document.xml": b"<w:document xmlns:w='urn:w'/>"}))
    with pytest.raises(ValueError, match="shape tree is missing"):
        extract_ooxml(_ooxml({"ppt/slides/slide1.xml": b"<p:sld xmlns:p='urn:p'/>"}))
    sheet = extract_ooxml(_ooxml({"xl/worksheets/sheet1.xml": b"<x xmlns='urn:x'><t>cell</t></x>"}))
    assert sheet[0].kind == "sheet"
    assert sheet[0].text == "cell"


def _ooxml(parts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def _pdf(*, stream: bytes) -> bytes:
    objects = (
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R >> endobj",
        b"4 0 obj << /Length "
        + str(len(stream)).encode()
        + b" >> stream\n"
        + stream
        + b"\nendstream endobj",
    )
    return b"%PDF-1.7\n" + b"\n".join(objects) + b"\n%%EOF\n"


def _deep_pdf(*, depth: int) -> bytes:
    objects = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj"]
    for object_number in range(2, depth + 2):
        child = object_number + 1
        objects.append(
            f"{object_number} 0 obj << /Type /Pages /Kids [{child} 0 R] /Count 1 >> endobj".encode()
        )
    page_number = depth + 2
    objects.append(
        f"{page_number} 0 obj << /Type /Page /Parent {page_number - 1} 0 R >> endobj".encode()
    )
    return b"%PDF-1.7\n" + b"\n".join(objects) + b"\n%%EOF\n"
