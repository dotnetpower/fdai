"""Adversarial tests for bounded document structure extraction."""

from __future__ import annotations

import io
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

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


def test_docx_preserves_nested_heading_context_and_table_roles() -> None:
    xml = b"""<w:document xmlns:w='urn:w'><w:body>
            <w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Operations</w:t></w:r></w:p>
            <w:p><w:pPr><w:pStyle w:val='Heading2'/></w:pPr><w:r><w:t>Backup</w:t></w:r></w:p>
            <w:p><w:r><w:t>Verify the snapshot.</w:t></w:r></w:p>
            <w:tbl>
                <w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p><w:r><w:t>Step</w:t></w:r></w:p></w:tc></w:tr>
                <w:tr><w:tc><w:p><w:r><w:t>Restore</w:t></w:r></w:p></w:tc></w:tr>
            </w:tbl>
        </w:body></w:document>"""

    units = extract_ooxml(_ooxml({"word/document.xml": xml}))

    assert units[2].locator == ("docx/paragraph:3/context:heading:1:1/heading:2:1")
    assert [unit.table_cell_role for unit in units[3:]] == ["header", "body"]


def test_pptx_preserves_multiple_paragraphs_per_shape() -> None:
    slide = b"""<p:sld xmlns:p='urn:p' xmlns:a='urn:a'><p:cSld><p:spTree><p:sp>
            <p:txBody>
                <a:p><a:r><a:t>First paragraph</a:t></a:r></a:p>
                <a:p><a:r><a:t>Second paragraph</a:t></a:r></a:p>
            </p:txBody>
        </p:sp></p:spTree></p:cSld></p:sld>"""

    units = extract_ooxml(_ooxml({"ppt/slides/slide1.xml": slide}))

    assert [unit.text for unit in units] == ["First paragraph", "Second paragraph"]
    assert [unit.locator for unit in units] == [
        "pptx/slide:1/shape:1/paragraph:1",
        "pptx/slide:1/shape:1/paragraph:2",
    ]


def test_pptx_extracts_every_table_within_one_shape() -> None:
    table = (
        b"<a:tbl><a:tblPr firstRow='1'/><a:tr><a:tc><a:txBody>"
        b"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
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
    assert [unit.table_cell_role for unit in units] == ["header", "header"]


def test_xlsx_preserves_cell_addresses_shared_strings_and_roles() -> None:
    shared = b"""<sst xmlns='urn:x'><si><t>Header</t></si><si><t>Body</t></si></sst>"""
    sheet = (
        b"<worksheet xmlns='urn:x'><sheetData>"
        b"<row r='1'><c r='B1' t='s'><v>0</v></c></row>"
        b"<row r='2'><c r='B2' t='s'><v>1</v></c>"
        b"<c r='C2' t='inlineStr'><is><t>Inline</t></is></c></row>"
        b"</sheetData></worksheet>"
    )

    units = extract_ooxml(
        _ooxml(
            {
                "xl/sharedStrings.xml": shared,
                "xl/worksheets/sheet2.xml": sheet,
            }
        )
    )

    assert [unit.locator for unit in units] == [
        "xlsx/sheet:2/cell:B1",
        "xlsx/sheet:2/cell:B2",
        "xlsx/sheet:2/cell:C2",
    ]
    assert [unit.text for unit in units] == ["Header", "Body", "Inline"]
    assert [unit.table_cell_role for unit in units] == [None, None, None]


def test_pdf_extracts_generated_fixture_and_rejects_encryption() -> None:
    units = extract_pdf_text(_generated_pdf("Generated operations manual"))
    assert [unit.locator for unit in units] == ["pdf/page:1/block:1"]
    assert [unit.text for unit in units] == ["Generated operations manual"]

    with pytest.raises(ValueError, match="encrypted"):
        extract_pdf_text(_generated_pdf("restricted", password="secret"))


def test_pdf_uses_strict_reader_and_sanitizes_parser_errors(monkeypatch) -> None:
    real_reader = document_pdf.PdfReader

    def strict_reader(stream, *, strict):
        assert strict is True
        return real_reader(stream, strict=strict)

    monkeypatch.setattr(document_pdf, "PdfReader", strict_reader)
    assert extract_pdf_text(_generated_pdf("strict"))[0].text == "strict"

    def broken_reader(stream, *, strict):
        del stream, strict
        raise PdfReadError("private document fragment")

    monkeypatch.setattr(document_pdf, "PdfReader", broken_reader)
    with pytest.raises(ValueError) as captured:
        extract_pdf_text(b"%PDF-1.7\nprivate document fragment\n%%EOF")
    assert str(captured.value) == "PDF parsing or text extraction failed"
    assert "private document fragment" not in str(captured.value)


def test_pdf_native_extraction_enforces_every_budget(monkeypatch) -> None:
    content = _generated_pdf("bounded text")
    limits = (
        ("_MAX_PDF_BYTES", 1, "bytes"),
        ("_MAX_PDF_PAGES", 0, "page count"),
        ("_MAX_PDF_OBJECTS", 0, "object count"),
        ("_MAX_UNITS", 0, "extracted text"),
        ("_MAX_CHARACTERS", 1, "extracted text"),
    )
    for attribute, value, message in limits:
        with monkeypatch.context() as context:
            context.setattr(document_pdf, attribute, value)
            with pytest.raises(ValueError, match=message):
                extract_pdf_text(content)


def test_pdf_text_blocks_preserve_page_local_order() -> None:
    assert document_pdf._page_text_blocks(" first line\n\nsecond   line ") == (
        "first line",
        "second line",
    )


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

    reordered_blocks = (
        StructuralUnit(unit_id="unit-2", kind="page", locator="page:1:line:2", text="second"),
        StructuralUnit(unit_id="unit-1", kind="page", locator="page:1:line:1", text="first"),
    )
    with pytest.raises(ValueError, match="ordered by page and block"):
        normalize_pdf_ocr_units(reordered_blocks)


def test_pdf_ocr_validates_locator_empty_output_and_budget(monkeypatch) -> None:
    valid = (
        StructuralUnit(unit_id="unit-1", kind="page", locator="pdf/page:2/ocr:7", text="  text  "),
    )
    assert normalize_pdf_ocr_units(valid)[0].locator == "pdf/page:2/ocr:7"
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


def _generated_pdf(text: str, *, password: str | None = None) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(password)
    writer.write(output)
    return output.getvalue()
