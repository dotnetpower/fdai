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
KOREAN_CLAIMS = (
    "체크아웃 서비스는 플랫폼 팀이 담당합니다.",
    "체크아웃 서비스는 결제 서비스에 의존합니다.",
    "체크아웃 서비스의 지연 시간은 250밀리초 미만이어야 합니다.",
    "체크아웃 서비스는 레거시 서비스에 의존하면 안 됩니다.",
)


@dataclass(frozen=True, slots=True)
class GoldenDocument:
    name: str
    media_type: str
    observed_format: str
    content: bytes
    language: str
    claims: tuple[str, ...]
    scanned: bool = False


def golden_documents() -> tuple[GoldenDocument, ...]:
    return (
        GoldenDocument(
            "manual.md",
            "text/markdown",
            "text",
            "\n".join(CLAIMS).encode(),
            "en",
            CLAIMS,
        ),
        GoldenDocument(
            "manual.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "ooxml",
            _docx(CLAIMS),
            "en",
            CLAIMS,
        ),
        GoldenDocument(
            "manual.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ooxml",
            _pptx(CLAIMS),
            "en",
            CLAIMS,
        ),
        GoldenDocument(
            "manual.pdf",
            "application/pdf",
            "pdf",
            _pdf(CLAIMS, scanned=False),
            "en",
            CLAIMS,
        ),
        GoldenDocument(
            "manual-scan.pdf",
            "application/pdf",
            "pdf",
            _pdf(CLAIMS, scanned=True),
            "en",
            CLAIMS,
            scanned=True,
        ),
        GoldenDocument(
            "manual-ko.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "ooxml",
            _docx(KOREAN_CLAIMS),
            "ko",
            KOREAN_CLAIMS,
        ),
        GoldenDocument(
            "manual-ko.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ooxml",
            _pptx(KOREAN_CLAIMS),
            "ko",
            KOREAN_CLAIMS,
        ),
        GoldenDocument(
            "manual-ko-scan.pdf",
            "application/pdf",
            "pdf",
            _pdf(KOREAN_CLAIMS, scanned=True),
            "ko",
            KOREAN_CLAIMS,
            scanned=True,
        ),
    )


def _docx(claims: tuple[str, ...]) -> bytes:
    paragraphs = b"".join(
        b"<w:p><w:r><w:t>" + claim.encode() + b"</w:t></w:r></w:p>" for claim in claims
    )
    xml = b"<w:document xmlns:w='urn:w'><w:body>" + paragraphs + b"</w:body></w:document>"
    return _ooxml({"word/document.xml": xml})


def _pptx(claims: tuple[str, ...]) -> bytes:
    shapes = b"".join(
        b"<p:sp><p:txBody><a:p><a:r><a:t>"
        + claim.encode()
        + b"</a:t></a:r></a:p></p:txBody></p:sp>"
        for claim in claims
    )
    slide = (
        b"<p:sld xmlns:p='urn:p' xmlns:a='urn:a'><p:cSld><p:spTree>"
        b"<p:nvGrpSpPr/><p:grpSpPr/>" + shapes + b"</p:spTree></p:cSld></p:sld>"
    )
    return _ooxml({"ppt/slides/slide1.xml": slide})


def _pdf(claims: tuple[str, ...], *, scanned: bool) -> bytes:
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
        for index, claim in enumerate(claims):
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


__all__ = ["CLAIMS", "KOREAN_CLAIMS", "GoldenDocument", "golden_documents"]
