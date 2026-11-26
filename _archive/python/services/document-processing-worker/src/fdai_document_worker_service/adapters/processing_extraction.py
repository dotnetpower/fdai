"""Signature inspection and bounded structural document extraction."""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pypdf
from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentExtractionUnavailableError,
    DocumentVersion,
    ExtractionUnavailableReason,
    ImageOcrProvider,
    ProtectionInspection,
    ProtectionState,
    ProviderUnavailableError,
    StructuralUnit,
    classify_document_intake,
)

from fdai_document_worker_service.adapters.ooxml import (
    OoxmlEmbeddedImage,
    OoxmlParserBudget,
    extract_ooxml,
    extract_ooxml_embedded_images,
)
from fdai_document_worker_service.adapters.processing_extraction_support import (
    _embedded_image_units,
    _format_mismatch,
    _image_media_type,
    _looks_like_text,
    _merge_pdf_units,
    _normalize_pdf_ocr_units,
    _ooxml_package_format,
    _pdf_inspection,
    _read_bounded,
    _text_units,
)

_PDF_ENCRYPT = re.compile(rb"/Encrypt\b")
_OCR_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/tiff"})


class SignatureProtectionInspector:
    """Classify bounded text, OOXML, PDF, image, and protected containers."""

    def __init__(self, *, max_input_bytes: int) -> None:
        self._max_input_bytes = max_input_bytes

    async def inspect(
        self, *, source_name: str, media_type_hint: str, chunks: AsyncIterator[bytes]
    ) -> ProtectionInspection:
        content = await _read_bounded(chunks, self._max_input_bytes)
        expected = classify_document_intake(source_name, media_type_hint)
        if content.startswith(b"%PDF-"):
            if expected.family != "pdf":
                return _format_mismatch()
            encrypted = _PDF_ENCRYPT.search(content) is not None
            return ProtectionInspection(
                ProtectionState.PASSWORD_ENCRYPTED if encrypted else ProtectionState.NONE,
                "pdf",
                "application/pdf",
                reason_code="pdf_encrypted" if encrypted else None,
            )
        if content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
            return ProtectionInspection(
                ProtectionState.PASSWORD_ENCRYPTED,
                "ole-encrypted-office",
                "application/x-ole-storage",
                reason_code="office_password_encrypted",
            )
        if content.startswith(b"PK\x03\x04"):
            if expected.family != "ooxml":
                return _format_mismatch()
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    infos = archive.infolist()
                    names = {item.filename.lower() for item in infos}
                    if any(item.flag_bits & 0x1 for item in infos):
                        return ProtectionInspection(
                            ProtectionState.PASSWORD_ENCRYPTED,
                            "encrypted-container",
                            "application/zip",
                            reason_code="encrypted_container",
                        )
                    package_format = _ooxml_package_format(names)
                    if "[content_types].xml" not in names or package_format is None:
                        return ProtectionInspection(
                            ProtectionState.UNKNOWN,
                            "malformed-ooxml",
                            "application/zip",
                            reason_code="malformed_ooxml_package",
                        )
                    if package_format != expected.format_id:
                        return _format_mismatch()
                    return ProtectionInspection(
                        ProtectionState.NONE,
                        "ooxml",
                        expected.media_types[0],
                    )
            except zipfile.BadZipFile:
                return ProtectionInspection(
                    ProtectionState.UNKNOWN,
                    "malformed-ooxml",
                    "application/zip",
                    reason_code="malformed_ooxml_package",
                )
        image_type = _image_media_type(content)
        if image_type:
            if expected.family != "image" or image_type not in expected.media_types:
                return _format_mismatch()
            return ProtectionInspection(ProtectionState.NONE, "image", image_type)
        if expected.family == "text" and _looks_like_text(content):
            content.decode("utf-8-sig")
            return ProtectionInspection(
                ProtectionState.NONE,
                "text",
                expected.media_types[0],
            )
        return ProtectionInspection(
            ProtectionState.UNKNOWN,
            "unknown",
            "application/octet-stream",
            reason_code="unknown_format_or_protection",
        )


class BoundedDocumentExtractor:
    """Extract cited structural units without executing source content."""

    def __init__(
        self,
        *,
        image_ocr: ImageOcrProvider,
        max_input_bytes: int,
        max_characters: int,
        ooxml_budget: OoxmlParserBudget | None = None,
    ) -> None:
        self._image_ocr = image_ocr
        self._max_input_bytes = max_input_bytes
        self._max_characters = max_characters
        self._ooxml_budget = ooxml_budget or OoxmlParserBudget(max_input_bytes=max_input_bytes)

    async def extract(
        self, *, version: DocumentVersion, chunks: AsyncIterator[bytes]
    ) -> DocumentEnvelope:
        content = await _read_bounded(chunks, self._max_input_bytes)
        observed = version.observed_format or "unknown"
        extractor_name = "service-bounded"
        extractor_version = "1.0.0"
        warnings: list[str] = []
        if version.cloud_knowledge is not None:
            from fdai_document_worker_service.adapters.cloud_knowledge import cloud_reference_units

            units = cloud_reference_units(version, content)
            extractor_name = "cloud-reference"
        elif observed == "text":
            units = _text_units(content.decode("utf-8-sig"))
        elif observed == "ooxml":
            units = extract_ooxml(content, budget=self._ooxml_budget)
            embedded = extract_ooxml_embedded_images(content, budget=self._ooxml_budget)
            embedded_units, embedded_warnings = await self._extract_embedded_images(
                version,
                embedded,
            )
            units += embedded_units
            warnings.extend(embedded_warnings)
        elif observed == "pdf":
            pdf_pages, image_pages = await asyncio.to_thread(_pdf_inspection, content)
            native_units = tuple(unit for unit in pdf_pages if unit is not None)
            requires_ocr = len(native_units) != len(pdf_pages) or any(image_pages)
            if not requires_ocr:
                units = native_units
                extractor_name = "pypdf"
                extractor_version = pypdf.__version__
            else:
                try:
                    ocr_units = _normalize_pdf_ocr_units(
                        await self._ocr_required(version=version, content=content)
                    )
                except DocumentExtractionUnavailableError:
                    if len(native_units) != len(pdf_pages):
                        raise
                    units = native_units
                    warnings.append("pdf_image_ocr_unavailable")
                else:
                    units = _merge_pdf_units(pdf_pages, ocr_units) if pdf_pages else ocr_units
        elif observed == "image":
            units = await self._ocr_required(version=version, content=content)
        else:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNSUPPORTED_FORMAT)
        if not units and any(
            warning.startswith("embedded_image_ocr_unavailable:") for warning in warnings
        ):
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.OCR_UNAVAILABLE)
        if not units:
            raise DocumentExtractionUnavailableError(
                ExtractionUnavailableReason.NO_EXTRACTABLE_CONTENT
            )
        if sum(len(unit.text) for unit in units) > self._max_characters:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.TEXT_BUDGET)
        return DocumentEnvelope(
            document_id=version.document_id,
            version_id=version.version_id,
            source_sha256=version.source_sha256,
            media_type=version.media_type,
            observed_format=observed,
            size_bytes=version.size_bytes,
            collection_id=version.access.collection_id,
            purposes=version.purposes,
            protection_state=version.protection_state,
            access_descriptor_ref=version.access.reference,
            units=units,
            extractor_name=extractor_name,
            extractor_version=extractor_version,
            warnings=tuple(warnings),
            cloud_knowledge=version.cloud_knowledge,
        )

    async def _ocr_required(
        self,
        *,
        version: DocumentVersion,
        content: bytes,
    ) -> tuple[StructuralUnit, ...]:
        try:
            units = await self._image_ocr.extract(version=version, content=content)
        except (ProviderUnavailableError, RuntimeError) as exc:
            raise DocumentExtractionUnavailableError(
                ExtractionUnavailableReason.OCR_UNAVAILABLE
            ) from exc
        if not units:
            raise DocumentExtractionUnavailableError(
                ExtractionUnavailableReason.NO_EXTRACTABLE_CONTENT
            )
        return units

    async def _extract_embedded_images(
        self,
        version: DocumentVersion,
        images: Sequence[OoxmlEmbeddedImage],
    ) -> tuple[tuple[StructuralUnit, ...], tuple[str, ...]]:
        units: list[StructuralUnit] = []
        unsupported = 0
        unavailable = 0
        no_text = 0
        for image_number, image in enumerate(images, start=1):
            media_type = _image_media_type(image.content)
            if media_type not in _OCR_IMAGE_MEDIA_TYPES:
                unsupported += 1
                continue
            image_version = version.model_copy(
                update={
                    "source_name": Path(image.part_name).name,
                    "media_type": media_type,
                    "observed_format": "image",
                }
            )
            try:
                extracted = await self._image_ocr.extract(
                    version=image_version,
                    content=image.content,
                )
            except (ProviderUnavailableError, RuntimeError):
                unavailable += 1
                continue
            if not extracted:
                no_text += 1
                continue
            units.extend(_embedded_image_units(extracted, image_number=image_number))
        warnings = tuple(
            warning
            for count, warning in (
                (unsupported, f"embedded_images_unsupported:{unsupported}"),
                (unavailable, f"embedded_image_ocr_unavailable:{unavailable}"),
                (no_text, f"embedded_images_without_text:{no_text}"),
            )
            if count
        )
        return tuple(units), warnings
