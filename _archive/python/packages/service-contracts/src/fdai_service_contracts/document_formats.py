"""Shared intake policy for governed document source formats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath


@dataclass(frozen=True, slots=True)
class DocumentFormatSpec:
    """One supported filename/media-type family exposed by capability discovery."""

    format_id: str
    family: str
    extensions: tuple[str, ...]
    media_types: tuple[str, ...]


DOCUMENT_FORMAT_SPECS: tuple[DocumentFormatSpec, ...] = (
    DocumentFormatSpec(
        "text",
        "text",
        (".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".xml", ".csv", ".tf", ".rego"),
        (
            "text/plain",
            "text/markdown",
            "text/csv",
            "application/json",
            "application/xml",
            "text/xml",
            "application/yaml",
        ),
    ),
    DocumentFormatSpec("pdf", "pdf", (".pdf",), ("application/pdf",)),
    DocumentFormatSpec(
        "docx",
        "ooxml",
        (".docx",),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    ),
    DocumentFormatSpec(
        "pptx",
        "ooxml",
        (".pptx",),
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    ),
    DocumentFormatSpec(
        "xlsx",
        "ooxml",
        (".xlsx",),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    ),
    DocumentFormatSpec("png", "image", (".png",), ("image/png",)),
    DocumentFormatSpec("jpeg", "image", (".jpg", ".jpeg"), ("image/jpeg",)),
    DocumentFormatSpec("tiff", "image", (".tif", ".tiff"), ("image/tiff",)),
)

_BY_EXTENSION = {extension: spec for spec in DOCUMENT_FORMAT_SPECS for extension in spec.extensions}
_LEGACY_OFFICE = {
    ".doc": ".docx or .pdf",
    ".ppt": ".pptx or .pdf",
    ".xls": ".xlsx or .pdf",
}
_GENERIC_MEDIA_TYPES = frozenset({"", "application/octet-stream", "application/zip"})


def supported_document_format_ids(*, include_ocr: bool = True) -> tuple[str, ...]:
    """Return stable format ids, omitting image-only sources when OCR is unavailable."""
    return tuple(
        spec.format_id for spec in DOCUMENT_FORMAT_SPECS if include_ocr or spec.family != "image"
    )


def supported_document_extensions() -> tuple[str, ...]:
    """Return every accepted extension in deterministic order."""
    return tuple(extension for spec in DOCUMENT_FORMAT_SPECS for extension in spec.extensions)


def classify_document_intake(source_name: str, media_type_hint: str) -> DocumentFormatSpec:
    """Validate an upload hint without treating it as authoritative content detection."""
    suffix = PurePath(source_name.strip()).suffix.casefold()
    if suffix in _LEGACY_OFFICE:
        raise ValueError(
            f"legacy Office format {suffix} is unsupported; save the source as "
            f"{_LEGACY_OFFICE[suffix]} before uploading"
        )
    spec = _BY_EXTENSION.get(suffix)
    if spec is None:
        raise ValueError(f"unsupported document format: {suffix or 'missing extension'}")
    media_type = media_type_hint.split(";", 1)[0].strip().casefold()
    if (
        media_type not in _GENERIC_MEDIA_TYPES
        and media_type not in spec.media_types
        and not (spec.family == "text" and media_type.startswith("text/"))
    ):
        raise ValueError(
            f"media type {media_type or 'missing'} does not match document format {spec.format_id}"
        )
    return spec
