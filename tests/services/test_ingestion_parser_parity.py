"""Focused parser-budget and OOXML structural parity tests."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace

import pytest
from fdai_document_worker_service.adapters.ooxml import OoxmlParserBudget, extract_ooxml
from fdai_service_contracts import DocumentExtractionUnavailableError, ExtractionUnavailableReason


def test_docx_preserves_heading_context_and_table_roles() -> None:
    xml = b"""<w:document xmlns:w='urn:w'><w:body>
        <w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Operations</w:t></w:r></w:p>
        <w:p><w:r><w:t>Verify the snapshot.</w:t></w:r></w:p>
        <w:tbl>
          <w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p><w:r><w:t>Step</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>Restore</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>
      </w:body></w:document>"""

    units = extract_ooxml(_ooxml({"word/document.xml": xml}), budget=OoxmlParserBudget())

    assert [unit.locator for unit in units] == [
        "docx/heading:1:1",
        "docx/paragraph:2/context:heading:1:1",
        "docx/table:1/row:1/cell:1",
        "docx/table:1/row:2/cell:1",
    ]
    assert [unit.table_cell_role for unit in units[2:]] == ["header", "body"]
    assert units[0].heading_level == 1
    assert units[1].parent_locator == "docx/heading:1:1"


def test_pptx_preserves_shape_paragraphs_tables_and_notes() -> None:
    slide = (
        b"<p:sld xmlns:p='urn:p' xmlns:a='urn:a'><p:cSld><p:spTree>"
        b"<p:sp><p:nvSpPr><p:cNvPr name='Summary'/></p:nvSpPr><p:txBody>"
        b"<a:p><a:r><a:t>First</a:t></a:r></a:p>"
        b"<a:p><a:r><a:t>Second</a:t></a:r></a:p>"
        b"</p:txBody></p:sp>"
        b"<p:graphicFrame><a:graphic><a:graphicData><a:tbl>"
        b"<a:tblPr firstRow='1'/><a:tr><a:tc><a:txBody>"
        b"<a:p><a:r><a:t>Header</a:t></a:r></a:p>"
        b"</a:txBody></a:tc></a:tr></a:tbl>"
        b"</a:graphicData></a:graphic></p:graphicFrame>"
        b"</p:spTree></p:cSld></p:sld>"
    )
    notes = (
        b"<p:notes xmlns:p='urn:p' xmlns:a='urn:a'>"
        b"<a:p><a:r><a:t>Speaker note</a:t></a:r></a:p>"
        b"</p:notes>"
    )

    units = extract_ooxml(
        _ooxml(
            {
                "ppt/slides/slide1.xml": slide,
                "ppt/slides/_rels/slide1.xml.rels": (
                    b"<Relationships><Relationship Id='rId8' "
                    b"Type='urn:office/relationships/notesSlide' "
                    b"Target='../notesSlides/notesSlide9.xml'/></Relationships>"
                ),
                "ppt/notesSlides/notesSlide9.xml": notes,
            }
        ),
        budget=OoxmlParserBudget(),
    )

    assert [unit.text for unit in units] == ["First", "Second", "Header", "Speaker note"]
    assert units[2].table_cell_role == "header"
    assert units[3].locator == "pptx/slide:1/notes:1"
    assert units[0].section_name == "Summary"


def test_xlsx_preserves_shared_strings_inline_text_and_cell_addresses() -> None:
    shared = b"<sst xmlns='urn:x'><si><t>Header</t></si></sst>"
    workbook = (
        b"<workbook xmlns='urn:x' xmlns:r='urn:r'><sheets>"
        b"<sheet name='Runbook' r:id='rId2'/></sheets></workbook>"
    )
    relationships = (
        b"<Relationships><Relationship Id='rId2' Target='worksheets/sheet2.xml'/></Relationships>"
    )
    sheet = (
        b"<worksheet xmlns='urn:x'><sheetData><row r='1'>"
        b"<c r='B1' t='s'><v>0</v></c>"
        b"<c r='C1' t='inlineStr'><is><t>Inline</t></is></c>"
        b"</row></sheetData></worksheet>"
    )

    units = extract_ooxml(
        _ooxml(
            {
                "xl/sharedStrings.xml": shared,
                "xl/workbook.xml": workbook,
                "xl/_rels/workbook.xml.rels": relationships,
                "xl/worksheets/sheet2.xml": sheet,
            }
        ),
        budget=OoxmlParserBudget(),
    )

    assert [unit.locator for unit in units] == [
        "xlsx/sheet:2/cell:B1",
        "xlsx/sheet:2/cell:C1",
    ]
    assert [unit.text for unit in units] == ["Header", "Inline"]
    assert {unit.section_name for unit in units} == {"Runbook"}


def test_ooxml_reports_explicit_unavailable_reasons_for_parser_budgets() -> None:
    content = _ooxml({"word/document.xml": b"<w:document xmlns:w='urn:w'><w:body/></w:document>"})
    with pytest.raises(DocumentExtractionUnavailableError) as members:
        extract_ooxml(content, budget=replace(OoxmlParserBudget(), max_members=1))
    assert members.value.reason is ExtractionUnavailableReason.PACKAGE_MEMBER_BUDGET
    with pytest.raises(DocumentExtractionUnavailableError) as member_bytes:
        extract_ooxml(content, budget=replace(OoxmlParserBudget(), max_xml_member_bytes=32))
    assert member_bytes.value.reason is ExtractionUnavailableReason.XML_MEMBER_BUDGET
    nested = b"<w:document xmlns:w='urn:w'><w:body><a><b><c/></b></a></w:body></w:document>"
    with pytest.raises(DocumentExtractionUnavailableError) as depth:
        extract_ooxml(
            _ooxml({"word/document.xml": nested}),
            budget=replace(OoxmlParserBudget(), max_xml_depth=3),
        )
    assert depth.value.reason is ExtractionUnavailableReason.XML_DEPTH_BUDGET
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../escape.xml", "x")
    with pytest.raises(DocumentExtractionUnavailableError) as unsafe:
        extract_ooxml(output.getvalue(), budget=OoxmlParserBudget())
    assert unsafe.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


def test_ooxml_enforces_node_and_extracted_text_budgets() -> None:
    xml = (
        b"<w:document xmlns:w='urn:w'><w:body><w:p><w:r>"
        b"<w:t>abcdef</w:t></w:r></w:p></w:body></w:document>"
    )
    content = _ooxml({"word/document.xml": xml})

    with pytest.raises(DocumentExtractionUnavailableError) as nodes:
        extract_ooxml(content, budget=replace(OoxmlParserBudget(), max_xml_nodes=4))
    assert nodes.value.reason is ExtractionUnavailableReason.XML_NODE_BUDGET
    with pytest.raises(DocumentExtractionUnavailableError) as text:
        extract_ooxml(content, budget=replace(OoxmlParserBudget(), max_text_characters=5))
    assert text.value.reason is ExtractionUnavailableReason.TEXT_BUDGET


def _ooxml(parts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()
