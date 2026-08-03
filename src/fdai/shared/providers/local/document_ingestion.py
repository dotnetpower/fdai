"""Local document adapters with bounded standard-library parsing."""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pypdf

from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentVersion,
    MalwareVerdict,
    ProtectionState,
    StructuralUnit,
    UploadSession,
)
from fdai.shared.providers.document_ingestion import (
    DocumentNotFoundError,
    ImageOcrProvider,
    ProtectionInspection,
    StoredObjectInfo,
    UploadGrant,
)
from fdai.shared.providers.local.document_structure import (
    extract_ooxml,
    extract_pdf_text,
    normalize_pdf_ocr_units,
    validated_zip_members,
)
from fdai.shared.providers.local.document_text import extract_structured_text

_MAX_PARSE_BYTES = 32 * 1024 * 1024
_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_PDF_ENCRYPT = re.compile(rb"/Encrypt\b")
_TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".xml", ".csv", ".tf", ".rego"}
)
_OOXML_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})


class LocalDirectoryDocumentObjectStore:
    """Opaque-key object store rooted under one local development directory."""

    def __init__(self, root: Path, *, chunk_size: int = 64 * 1024) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._chunk_size = chunk_size
        self._revoked: set[UUID] = set()

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(session.upload_id, f"local://{session.upload_id}", session.expires_at)

    async def resume_upload(self, session: UploadSession) -> UploadGrant:
        if session.upload_id in self._revoked:
            raise ValueError("upload grant has been revoked")
        return await self.issue_upload(session)

    async def put(self, object_key: str, content: bytes) -> StoredObjectInfo:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)
        return StoredObjectInfo(object_key, len(content), hashlib.sha256(content).hexdigest())

    async def stat(self, object_key: str) -> StoredObjectInfo:
        path = self._path(object_key)
        if not path.is_file():
            raise DocumentNotFoundError("source object was not found")
        return await asyncio.to_thread(_stat_file, path, object_key)

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        path = self._path(object_key)
        if not path.is_file():
            raise DocumentNotFoundError("source object was not found")
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, self._chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def revoke_upload(self, upload_id: UUID) -> None:
        self._revoked.add(upload_id)

    async def delete(self, object_key: str) -> None:
        path = self._path(object_key)
        if path.exists():
            await asyncio.to_thread(path.unlink)

    def _path(self, object_key: str) -> Path:
        path = (self._root / object_key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("object key escapes the configured storage root")
        return path


class UnavailableMalwareScanner:
    """Production-safe upstream default: abstain instead of claiming a scan."""

    async def scan(self, chunks: AsyncIterator[bytes]) -> MalwareVerdict:
        async for _ in chunks:
            break
        return MalwareVerdict.UNAVAILABLE


class SignatureProtectionInspector:
    """Classify common text, OOXML, PDF, encryption, and unknown signatures."""

    async def inspect(
        self, *, source_name: str, media_type_hint: str, chunks: AsyncIterator[bytes]
    ) -> ProtectionInspection:
        content = await _read_bounded(chunks)
        suffix = Path(source_name).suffix.lower()
        if content.startswith(b"%PDF-"):
            state = (
                ProtectionState.PASSWORD_ENCRYPTED
                if _PDF_ENCRYPT.search(content)
                else ProtectionState.NONE
            )
            return ProtectionInspection(
                state=state,
                observed_format="pdf",
                media_type="application/pdf",
                reason_code="pdf_encrypted" if state is not ProtectionState.NONE else None,
            )
        if content.startswith(_OLE_SIGNATURE) and suffix in _OOXML_EXTENSIONS:
            return ProtectionInspection(
                state=ProtectionState.PASSWORD_ENCRYPTED,
                observed_format="ole-encrypted-office",
                media_type="application/x-ole-storage",
                reason_code="office_password_encrypted",
            )
        if content.startswith(b"PK\x03\x04"):
            return _inspect_zip(content, suffix)
        image_type = _image_media_type(content)
        if image_type is not None:
            return ProtectionInspection(
                state=ProtectionState.NONE,
                observed_format="image",
                media_type=image_type,
            )
        if suffix in _TEXT_EXTENSIONS or _looks_like_text(content):
            _decode_text(content)
            return ProtectionInspection(
                state=ProtectionState.NONE,
                observed_format="text",
                media_type=media_type_hint or "text/plain",
            )
        return ProtectionInspection(
            state=ProtectionState.UNKNOWN,
            observed_format="unknown",
            media_type="application/octet-stream",
            reason_code="unknown_format_or_protection",
        )


class StandardLibraryDocumentExtractor:
    """Extract bounded local text, Office, PDF, and OCR evidence without active content."""

    def __init__(self, *, image_ocr: ImageOcrProvider | None = None) -> None:
        self._image_ocr = image_ocr

    async def extract(
        self, *, version: DocumentVersion, chunks: AsyncIterator[bytes]
    ) -> DocumentEnvelope:
        content = await _read_bounded(chunks)
        observed = version.observed_format or "unknown"
        if observed == "text":
            _decode_text(content)
            units = extract_structured_text(content, source_name=version.source_name)
        elif observed == "ooxml":
            units = extract_ooxml(content)
        elif observed == "pdf":
            units = extract_pdf_text(content)
            if not units:
                if self._image_ocr is None:
                    raise ValueError("scanned PDF extraction requires an OCR provider")
                units = normalize_pdf_ocr_units(
                    await self._image_ocr.extract(version=version, content=content)
                )
        elif observed == "image":
            units = (
                await self._image_ocr.extract(version=version, content=content)
                if self._image_ocr is not None
                else ()
            )
        else:
            raise ValueError("no safe standard-library extractor is available for this format")
        _validate_unit_kinds(observed, units)
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
            extractor_name="pypdf" if observed == "pdf" else "stdlib-safe",
            extractor_version=pypdf.__version__ if observed == "pdf" else "1.1.0",
        )


def _validate_unit_kinds(observed_format: str, units: tuple[StructuralUnit, ...]) -> None:
    expected = {
        "text": frozenset({"text", "paragraph", "table"}),
        "ooxml": frozenset({"paragraph", "table", "slide", "sheet"}),
        "pdf": frozenset({"page"}),
        "image": frozenset({"page"}),
    }.get(observed_format)
    if expected is None or any(unit.kind not in expected for unit in units):
        raise ValueError("extracted structural unit kind does not match the observed format")


def _image_media_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _read_bounded(chunks: AsyncIterator[bytes]) -> bytes:
    content = bytearray()
    async for chunk in chunks:
        content.extend(chunk)
        if len(content) > _MAX_PARSE_BYTES:
            raise ValueError("document exceeds the local parser byte budget")
    return bytes(content)


def _inspect_zip(content: bytes, suffix: str) -> ProtectionInspection:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = validated_zip_members(archive)
        names = {item.filename.lower() for item in infos}
        if any(item.flag_bits & 0x1 for item in infos) or {
            "encryptioninfo",
            "encryptedpackage",
        }.intersection(names):
            return ProtectionInspection(
                ProtectionState.PASSWORD_ENCRYPTED,
                "encrypted-container",
                "application/zip",
                reason_code="encrypted_container",
            )
        if any("drm" in name or "rightsmanagement" in name for name in names):
            return ProtectionInspection(
                ProtectionState.UNSUPPORTED_PROTECTION,
                "protected-ooxml",
                "application/zip",
                reason_code="rights_managed_container",
            )
        if "[content_types].xml" in names and suffix in _OOXML_EXTENSIONS:
            return ProtectionInspection(
                ProtectionState.NONE,
                "ooxml",
                _ooxml_media_type(suffix),
            )
    return ProtectionInspection(
        ProtectionState.UNSUPPORTED_PROTECTION,
        "zip",
        "application/zip",
        reason_code="archives_disabled",
    )


def _looks_like_text(content: bytes) -> bool:
    if b"\x00" in content[:4096]:
        return False
    sample = content[:4096]
    if not sample:
        return True
    controls = sum(byte < 32 and byte not in (9, 10, 13) for byte in sample)
    return controls / len(sample) < 0.02


def _decode_text(content: bytes) -> str:
    if not _looks_like_text(content):
        raise ValueError("binary content cannot be extracted as text")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("text content is not valid UTF-8") from exc


def _ooxml_media_type(suffix: str) -> str:
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[suffix]


def _stat_file(path: Path, object_key: str) -> StoredObjectInfo:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return StoredObjectInfo(object_key, size, digest.hexdigest())


__all__ = [
    "LocalDirectoryDocumentObjectStore",
    "SignatureProtectionInspector",
    "StandardLibraryDocumentExtractor",
    "UnavailableMalwareScanner",
]
