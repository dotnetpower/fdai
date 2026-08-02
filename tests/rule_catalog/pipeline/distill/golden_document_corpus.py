"""Deterministic multi-format corpus for document ontology conformance."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

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
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
    ]
    if scanned:
        objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj")
    else:
        stream = b"\n".join(b"BT (" + claim.encode() + b") Tj ET" for claim in CLAIMS)
        objects.extend(
            (
                b"3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R >> endobj",
                b"4 0 obj << /Length "
                + str(len(stream)).encode()
                + b" >> stream\n"
                + stream
                + b"\nendstream endobj",
            )
        )
    return b"%PDF-1.7\n" + b"\n".join(objects) + b"\n%%EOF\n"


def _ooxml(parts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


__all__ = ["CLAIMS", "GoldenDocument", "golden_documents"]
