"""Focused parser-budget and OOXML structural parity tests."""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fdai_document_worker_service.adapters import processing as processing_module
from fdai_document_worker_service.adapters.ooxml import (
    OoxmlParserBudget,
    extract_ooxml,
    extract_ooxml_embedded_images,
)
from fdai_document_worker_service.adapters.pdf_isolation import PdfPageInspection
from fdai_document_worker_service.adapters.processing import (
    BoundedDocumentExtractor,
    SignatureProtectionInspector,
    UnavailableImageOcr,
)
from fdai_service_contracts import (
    AccessDescriptor,
    DocumentExtractionUnavailableError,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ExtractionUnavailableReason,
    ProtectionState,
    RetentionPolicy,
    StructuralUnit,
)


class _ImageOcr:
    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        del version, content
        return (
            StructuralUnit(
                unit_id="ocr-1",
                kind="page",
                locator="page:1:line:1",
                text="Scanned text",
            ),
        )


class _MixedPdfOcr:
    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        del version, content
        return (
            StructuralUnit(
                unit_id="ocr-1",
                kind="page",
                locator="page:1:line:1",
                text="Native text",
            ),
            StructuralUnit(
                unit_id="ocr-2",
                kind="page",
                locator="page:2:line:1",
                text="Scanned text",
            ),
        )


class _IncompletePdfOcr:
    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        del version, content
        return (
            StructuralUnit(
                unit_id="ocr-1",
                kind="page",
                locator="page:1:line:1",
                text="Native text",
            ),
        )


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _pdf_version() -> DocumentVersion:
    now = datetime.now(UTC)
    return DocumentVersion(
        document_id=uuid4(),
        version_id=uuid4(),
        upload_id=uuid4(),
        source_name="scan.pdf",
        source_sha256="0" * 64,
        size_bytes=4,
        media_type="application/pdf",
        observed_format="pdf",
        state=DocumentState.EXTRACTING,
        protection_state=ProtectionState.NONE,
        access=AccessDescriptor(reference="collection:test", collection_id="test"),
        retention=RetentionPolicy(policy_version="test"),
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        uploader_id="test-operator",
        created_at=now,
        updated_at=now,
    )


async def test_input_byte_budget_reports_typed_extraction_reason() -> None:
    with pytest.raises(DocumentExtractionUnavailableError) as exceeded:
        await processing_module._read_bounded(_chunks(b"1234"), 3)

    assert exceeded.value.reason is ExtractionUnavailableReason.INPUT_BUDGET


def test_native_pdf_uses_canonical_page_block_locator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        processing_module,
        "inspect_pdf_pages_isolated",
        lambda _content: (PdfPageInspection("Native text", False),),
    )

    units, image_pages = processing_module._pdf_inspection(b"pdf")

    assert [unit.locator for unit in units] == ["pdf/page:1/block:1"]
    assert image_pages == (False,)


async def test_scanned_pdf_reports_ocr_extractor_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        processing_module,
        "_pdf_inspection",
        lambda _content: ((None,), (True,)),
    )
    extractor = BoundedDocumentExtractor(
        image_ocr=_ImageOcr(),
        max_input_bytes=1024,
        max_characters=1024,
    )

    envelope = await extractor.extract(version=_pdf_version(), chunks=_chunks(b"scan"))

    assert envelope.extractor_name == "service-bounded"
    assert envelope.extractor_version == "1.0.0"
    assert [unit.text for unit in envelope.units] == ["Scanned text"]


async def test_mixed_pdf_uses_ocr_only_for_pages_without_native_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        processing_module,
        "_pdf_inspection",
        lambda _content: (
            (
                StructuralUnit(
                    unit_id="page-1",
                    kind="page",
                    locator="pdf/page:1/block:1",
                    text="Native text",
                ),
                None,
            ),
            (False, True),
        ),
    )
    extractor = BoundedDocumentExtractor(
        image_ocr=_MixedPdfOcr(),
        max_input_bytes=1024,
        max_characters=1024,
    )

    envelope = await extractor.extract(version=_pdf_version(), chunks=_chunks(b"pdf"))

    assert envelope.extractor_name == "service-bounded"
    assert [unit.locator for unit in envelope.units] == [
        "pdf/page:1/block:1",
        "pdf/page:2/ocr:1",
    ]
    assert [unit.text for unit in envelope.units] == ["Native text", "Scanned text"]


async def test_mixed_pdf_fails_closed_when_scanned_page_has_no_ocr_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        processing_module,
        "_pdf_inspection",
        lambda _content: (
            (
                StructuralUnit(
                    unit_id="page-1",
                    kind="page",
                    locator="pdf/page:1/block:1",
                    text="Native text",
                ),
                None,
            ),
            (False, True),
        ),
    )
    extractor = BoundedDocumentExtractor(
        image_ocr=_IncompletePdfOcr(),
        max_input_bytes=1024,
        max_characters=1024,
    )

    with pytest.raises(ValueError, match="no cited text for page 2"):
        await extractor.extract(version=_pdf_version(), chunks=_chunks(b"pdf"))


async def test_native_pdf_page_with_image_merges_nonduplicate_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = StructuralUnit(
        unit_id="page-1",
        kind="page",
        locator="pdf/page:1/block:1",
        text="Native text",
    )
    monkeypatch.setattr(
        processing_module,
        "_pdf_inspection",
        lambda _content: ((native,), (True,)),
    )
    envelope = await BoundedDocumentExtractor(
        image_ocr=_ImageOcr(),
        max_input_bytes=1024,
        max_characters=1024,
    ).extract(version=_pdf_version(), chunks=_chunks(b"pdf"))
    assert [unit.text for unit in envelope.units] == ["Native text", "Scanned text"]


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


@pytest.mark.parametrize(
    ("notes_target", "notes_name"),
    [
        ("../notesSlides/notesSlide9.xml", "ppt/notesSlides/notesSlide9.xml"),
        ("../../notesSlides/notesSlide9.xml", "notesSlides/notesSlide9.xml"),
    ],
)
def test_pptx_preserves_shape_paragraphs_tables_and_notes(
    notes_target: str,
    notes_name: str,
) -> None:
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
                    + f"Target='{notes_target}'/></Relationships>".encode()
                ),
                notes_name: notes,
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


def test_xlsx_preserves_formula_as_text_without_execution() -> None:
    sheet = (
        b"<worksheet xmlns='urn:x'><sheetData><row r='1'>"
        b"<c r='A1'><f>SUM(B1:B2)</f><v>7</v></c>"
        b"</row></sheetData></worksheet>"
    )
    units = extract_ooxml(
        _ooxml(
            {
                "xl/workbook.xml": b"<workbook/>",
                "xl/worksheets/sheet1.xml": sheet,
            }
        ),
        budget=OoxmlParserBudget(),
    )
    assert units[0].text == "=SUM(B1:B2) [cached: 7]"


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
    symlink_output = io.BytesIO()
    with zipfile.ZipFile(symlink_output, "w") as archive:
        link = zipfile.ZipInfo("word/media/link.png")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "target")
    with pytest.raises(DocumentExtractionUnavailableError) as symlink:
        extract_ooxml_embedded_images(
            symlink_output.getvalue(),
            budget=OoxmlParserBudget(),
        )
    assert symlink.value.reason is ExtractionUnavailableReason.UNSAFE_PACKAGE


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


def test_malformed_ooxml_xml_reports_typed_package_failure() -> None:
    with pytest.raises(DocumentExtractionUnavailableError) as malformed:
        extract_ooxml(
            _ooxml({"word/document.xml": b"<w:document><w:body></w:document>"}),
            budget=OoxmlParserBudget(),
        )
    assert malformed.value.reason is ExtractionUnavailableReason.MALFORMED_PACKAGE


def test_ooxml_embedded_images_are_bounded_and_sorted() -> None:
    content = _ooxml(
        {
            "word/document.xml": b"<w:document xmlns:w='urn:w'><w:body/></w:document>",
            "word/_rels/document.xml.rels": (
                b"<Relationships><Relationship Type='urn:office/relationships/image' "
                b"Target='media/image2.png'/><Relationship "
                b"Type='urn:office/relationships/image' Target='media/image1.jpeg'/>"
                b"</Relationships>"
            ),
            "word/media/image2.png": b"\x89PNG\r\n\x1a\nsecond",
            "word/media/image1.jpeg": b"\xff\xd8\xfffirst",
            "word/media/orphan.png": b"\x89PNG\r\n\x1a\norphan",
        }
    )
    images = extract_ooxml_embedded_images(content, budget=OoxmlParserBudget())
    assert [image.part_name for image in images] == [
        "word/media/image1.jpeg",
        "word/media/image2.png",
    ]
    with pytest.raises(DocumentExtractionUnavailableError) as members:
        extract_ooxml_embedded_images(
            content,
            budget=replace(OoxmlParserBudget(), max_media_members=1),
        )
    assert members.value.reason is ExtractionUnavailableReason.PACKAGE_MEMBER_BUDGET


@pytest.mark.parametrize(
    ("relationship_name", "target", "media_name"),
    [
        ("word/_rels/document.xml.rels", "media/image1.png", "word/media/image1.png"),
        (
            "ppt/slides/_rels/slide1.xml.rels",
            "../media/image1.png",
            "ppt/media/image1.png",
        ),
        (
            "xl/drawings/_rels/drawing1.xml.rels",
            "../media/image1.png",
            "xl/media/image1.png",
        ),
    ],
)
def test_ooxml_resolves_only_referenced_embedded_images(
    relationship_name: str,
    target: str,
    media_name: str,
) -> None:
    relationship = (
        b"<Relationships><Relationship Type='urn:office/relationships/image' Target='"
        + target.encode()
        + b"'/></Relationships>"
    )
    images = extract_ooxml_embedded_images(
        _ooxml(
            {
                relationship_name: relationship,
                media_name: b"\x89PNG\r\n\x1a\nreferenced",
                media_name.replace("image1", "orphan"): b"\x89PNG\r\n\x1a\norphan",
            }
        ),
        budget=OoxmlParserBudget(),
    )
    assert [image.part_name for image in images] == [media_name]


async def test_ooxml_embedded_images_add_cited_ocr_units() -> None:
    content = _ooxml(
        {
            "word/document.xml": (
                b"<w:document xmlns:w='urn:w'><w:body>"
                b"<w:p><w:r><w:t>Native text</w:t></w:r></w:p>"
                b"</w:body></w:document>"
            ),
            "word/_rels/document.xml.rels": (
                b"<Relationships><Relationship Type='urn:office/relationships/image' "
                b"Target='media/image1.png'/></Relationships>"
            ),
            "word/media/image1.png": b"\x89PNG\r\n\x1a\nimage",
        }
    )
    version = _pdf_version().model_copy(
        update={
            "source_name": "runbook.docx",
            "media_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "observed_format": "ooxml",
        }
    )
    envelope = await BoundedDocumentExtractor(
        image_ocr=_ImageOcr(),
        max_input_bytes=1024 * 1024,
        max_characters=1024,
    ).extract(version=version, chunks=_chunks(content))
    assert [unit.text for unit in envelope.units] == ["Native text", "Scanned text"]
    assert envelope.units[-1].locator == "ooxml/embedded-image:1/ocr:1"


async def test_ooxml_embedded_image_ocr_unavailability_is_explicit() -> None:
    content = _ooxml(
        {
            "word/document.xml": (
                b"<w:document xmlns:w='urn:w'><w:body>"
                b"<w:p><w:r><w:t>Native text</w:t></w:r></w:p>"
                b"</w:body></w:document>"
            ),
            "word/_rels/document.xml.rels": (
                b"<Relationships><Relationship Type='urn:office/relationships/image' "
                b"Target='media/image1.png'/></Relationships>"
            ),
            "word/media/image1.png": b"\x89PNG\r\n\x1a\nimage",
        }
    )
    version = _pdf_version().model_copy(
        update={
            "source_name": "runbook.docx",
            "media_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "observed_format": "ooxml",
        }
    )
    envelope = await BoundedDocumentExtractor(
        image_ocr=UnavailableImageOcr(),
        max_input_bytes=1024 * 1024,
        max_characters=1024,
    ).extract(version=version, chunks=_chunks(content))
    assert envelope.warnings == ("embedded_image_ocr_unavailable:1",)


async def test_image_only_ooxml_requires_available_ocr() -> None:
    content = _ooxml(
        {
            "word/document.xml": b"<w:document xmlns:w='urn:w'><w:body/></w:document>",
            "word/_rels/document.xml.rels": (
                b"<Relationships><Relationship Type='urn:office/relationships/image' "
                b"Target='media/image1.png'/></Relationships>"
            ),
            "word/media/image1.png": b"\x89PNG\r\n\x1a\nimage",
        }
    )
    version = _pdf_version().model_copy(
        update={
            "source_name": "scan.docx",
            "media_type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "observed_format": "ooxml",
        }
    )
    with pytest.raises(DocumentExtractionUnavailableError) as unavailable:
        await BoundedDocumentExtractor(
            image_ocr=UnavailableImageOcr(),
            max_input_bytes=1024 * 1024,
            max_characters=1024,
        ).extract(version=version, chunks=_chunks(content))
    assert unavailable.value.reason is ExtractionUnavailableReason.OCR_UNAVAILABLE


async def test_signature_inspector_accepts_tiff_and_rejects_mismatched_content() -> None:
    inspector = SignatureProtectionInspector(max_input_bytes=1024)
    tiff = await inspector.inspect(
        source_name="scan.tiff",
        media_type_hint="image/tiff",
        chunks=_chunks(b"II*\x00payload"),
    )
    mismatch = await inspector.inspect(
        source_name="scan.pdf",
        media_type_hint="application/pdf",
        chunks=_chunks(b"\x89PNG\r\n\x1a\npayload"),
    )
    assert (tiff.observed_format, tiff.media_type) == ("image", "image/tiff")
    assert mismatch.reason_code == "format_signature_mismatch"


@pytest.mark.parametrize(
    ("source_name", "media_type", "package_part", "observed_media_type"),
    [
        (
            "runbook.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "word/document.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ppt/presentation.xml",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (
            "data.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
async def test_signature_inspector_distinguishes_modern_office_packages(
    source_name: str,
    media_type: str,
    package_part: str,
    observed_media_type: str,
) -> None:
    inspector = SignatureProtectionInspector(max_input_bytes=4096)
    result = await inspector.inspect(
        source_name=source_name,
        media_type_hint=media_type,
        chunks=_chunks(_ooxml({package_part: b"<root/>"})),
    )
    assert (result.observed_format, result.media_type) == ("ooxml", observed_media_type)


async def test_signature_inspector_rejects_renamed_ooxml_package() -> None:
    inspector = SignatureProtectionInspector(max_input_bytes=4096)
    result = await inspector.inspect(
        source_name="slides.docx",
        media_type_hint=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        chunks=_chunks(_ooxml({"ppt/presentation.xml": b"<root/>"})),
    )
    assert result.reason_code == "format_signature_mismatch"


def _ooxml(parts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()
