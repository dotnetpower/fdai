"""Deterministic multi-format corpus for document ontology conformance."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

CLAIMS = (
    "Checkout service is owned by Platform team.",
    "Checkout service depends on Billing service.",
    "Checkout service must keep latency below 250 ms.",
    "Checkout service must not depend on Legacy service.",
)


@dataclass(frozen=True, slots=True)
class GoldenDocument:
    name: str
    media_type: str
    observed_format: str
    content: bytes
    scanned: bool = False


def golden_documents() -> tuple[GoldenDocument, ...]:
    return (
        GoldenDocument("manual.md", "text/markdown", "text", "\n".join(CLAIMS).encode()),
        GoldenDocument(
            "manual.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "ooxml",
            _docx(),
        ),
        GoldenDocument(
            "manual.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ooxml",
            _pptx(),
        ),
        GoldenDocument("manual.pdf", "application/pdf", "pdf", _pdf(scanned=False)),
        GoldenDocument(
            "manual-scan.pdf",
            "application/pdf",
            "pdf",
            _pdf(scanned=True),
            scanned=True,
        ),
    )


def _docx() -> bytes:
    paragraphs = b"".join(
        b"<w:p><w:r><w:t>" + claim.encode() + b"</w:t></w:r></w:p>" for claim in CLAIMS
    )
    xml = b"<w:document xmlns:w='urn:w'><w:body>" + paragraphs + b"</w:body></w:document>"
    return _ooxml({"word/document.xml": xml})


def _pptx() -> bytes:
    shapes = b"".join(
        b"<p:sp><p:txBody><a:p><a:r><a:t>"
        + claim.encode()
        + b"</a:t></a:r></a:p></p:txBody></p:sp>"
        for claim in CLAIMS
    )
    slide = (
        b"<p:sld xmlns:p='urn:p' xmlns:a='urn:a'><p:cSld><p:spTree>"
        b"<p:nvGrpSpPr/><p:grpSpPr/>" + shapes + b"</p:spTree></p:cSld></p:sld>"
    )
    return _ooxml({"ppt/slides/slide1.xml": slide})


def _pdf(*, scanned: bool) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if not scanned:
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
        operations = ["BT /F1 12 Tf 72 720 Td"]
        for index, claim in enumerate(CLAIMS):
            if index:
                operations.append("0 -18 Td")
            escaped = claim.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            operations.append(f"({escaped}) Tj")
        operations.append("ET")
        stream = DecodedStreamObject()
        stream.set_data(" ".join(operations).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(output)
    return output.getvalue()


def _ooxml(parts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


__all__ = ["CLAIMS", "GoldenDocument", "golden_documents"]
