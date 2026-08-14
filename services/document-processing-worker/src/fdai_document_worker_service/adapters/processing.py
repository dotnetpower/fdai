"""Concrete scanning, extraction, OCR, embedding, and indexing providers."""

from __future__ import annotations

import asyncio
import io
import json
import re
import struct
import zipfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
import psycopg
import pypdf
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentEnvelope,
    DocumentExtractionUnavailableError,
    DocumentVersion,
    ExtractionUnavailableReason,
    ImageOcrProvider,
    MalwareVerdict,
    ProtectionInspection,
    ProtectionState,
    ProviderUnavailableError,
    StructuralUnit,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
    unavailable_readiness,
)

from fdai_document_worker_service.adapters.ooxml import OoxmlParserBudget, extract_ooxml

_TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".xml", ".csv", ".tf", ".rego"}
)
_OOXML_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})
_PDF_ENCRYPT = re.compile(rb"/Encrypt\b")
_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True, slots=True)
class ClamAvScannerConfig:
    host: str = "127.0.0.1"
    port: int = 3310
    timeout_seconds: float = 60.0
    max_stream_bytes: int = 32 * 1024 * 1024


class ClamAvMalwareScanner:
    """Scan one bounded stream through the replica-local ClamAV sidecar."""

    def __init__(self, *, config: ClamAvScannerConfig) -> None:
        self._config = config

    def readiness(self) -> AdapterReadiness:
        """Report validated replica-local clamd composition without opening a socket."""
        return configured_readiness("clamav")

    async def probe_readiness(self) -> AdapterReadiness:
        """Require a live clamd engine with a loaded signature database."""
        adapter = "clamav"
        try:
            async with asyncio.timeout(min(self._config.timeout_seconds, 5.0)):
                ping = await self._command(b"zPING\0")
                version = await self._command(b"zVERSION\0")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except (
            OSError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            UnicodeError,
        ) as exc:
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        if ping != "PONG\0":
            return live_unavailable_readiness(adapter, "unexpected_ping_response")
        if not _clamav_version_has_signatures(version):
            return live_unavailable_readiness(adapter, "signature_database_unavailable")
        return live_readiness(adapter)

    async def scan(self, chunks: AsyncIterator[bytes]) -> MalwareVerdict:
        try:
            return await asyncio.wait_for(self._scan(chunks), self._config.timeout_seconds)
        except (OSError, TimeoutError, asyncio.IncompleteReadError, ValueError):
            return MalwareVerdict.UNAVAILABLE

    async def _scan(self, chunks: AsyncIterator[bytes]) -> MalwareVerdict:
        reader, writer = await asyncio.open_connection(self._config.host, self._config.port)
        observed = 0
        try:
            writer.write(b"zINSTREAM\0")
            async for chunk in chunks:
                if not chunk:
                    continue
                observed += len(chunk)
                if observed > self._config.max_stream_bytes:
                    raise ValueError("document exceeds the ClamAV stream budget")
                writer.write(struct.pack(">I", len(chunk)))
                writer.write(chunk)
                await writer.drain()
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            response = (await reader.readuntil(b"\0")).decode(errors="replace")
        finally:
            writer.close()
            await writer.wait_closed()
        if response.endswith(" OK\0"):
            return MalwareVerdict.CLEAN
        if " FOUND\0" in response:
            return MalwareVerdict.INFECTED
        return MalwareVerdict.UNAVAILABLE

    async def _command(self, command: bytes) -> str:
        reader, writer = await asyncio.open_connection(self._config.host, self._config.port)
        try:
            writer.write(command)
            await writer.drain()
            return (await reader.readuntil(b"\0")).decode("ascii")
        finally:
            writer.close()
            await writer.wait_closed()


def _clamav_version_has_signatures(response: str) -> bool:
    parts = response.rstrip("\0\r\n").split("/", 2)
    if len(parts) != 3 or not parts[0].startswith("ClamAV "):
        return False
    engine_version = parts[0].removeprefix("ClamAV ").strip()
    signature_revision = parts[1].strip()
    signature_timestamp = parts[2].strip()
    return (
        bool(engine_version)
        and signature_revision.isdecimal()
        and int(signature_revision) > 0
        and bool(signature_timestamp)
        and signature_timestamp.casefold() != "unknown"
    )


class SignatureProtectionInspector:
    """Classify bounded text, OOXML, PDF, image, and protected containers."""

    def __init__(self, *, max_input_bytes: int) -> None:
        self._max_input_bytes = max_input_bytes

    async def inspect(
        self, *, source_name: str, media_type_hint: str, chunks: AsyncIterator[bytes]
    ) -> ProtectionInspection:
        content = await _read_bounded(chunks, self._max_input_bytes)
        suffix = Path(source_name).suffix.lower()
        if content.startswith(b"%PDF-"):
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
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    infos = archive.infolist()
                    names = {item.filename.lower() for item in infos}
                    if any(item.flag_bits & 0x1 for item in infos):
                        raise RuntimeError("encrypted")
                    if "[content_types].xml" in names and suffix in _OOXML_EXTENSIONS:
                        return ProtectionInspection(
                            ProtectionState.NONE,
                            "ooxml",
                            _ooxml_media_type(suffix),
                        )
            except (zipfile.BadZipFile, RuntimeError):
                return ProtectionInspection(
                    ProtectionState.PASSWORD_ENCRYPTED,
                    "encrypted-container",
                    "application/zip",
                    reason_code="encrypted_container",
                )
            return ProtectionInspection(
                ProtectionState.UNSUPPORTED_PROTECTION,
                "zip",
                "application/zip",
                reason_code="archives_disabled",
            )
        image_type = _image_media_type(content)
        if image_type:
            return ProtectionInspection(ProtectionState.NONE, "image", image_type)
        if suffix in _TEXT_EXTENSIONS or _looks_like_text(content):
            content.decode("utf-8-sig")
            return ProtectionInspection(
                ProtectionState.NONE,
                "text",
                media_type_hint or "text/plain",
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
        if observed == "text":
            units = _text_units(content.decode("utf-8-sig"))
        elif observed == "ooxml":
            units = extract_ooxml(content, budget=self._ooxml_budget)
        elif observed == "pdf":
            units = _pdf_units(content)
            if units:
                extractor_name = "pypdf"
                extractor_version = pypdf.__version__
            else:
                units = await self._image_ocr.extract(version=version, content=content)
        elif observed == "image":
            units = await self._image_ocr.extract(version=version, content=content)
        else:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.UNSUPPORTED_FORMAT)
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
        )


@dataclass(frozen=True, slots=True)
class AzureDocumentOcrConfig:
    endpoint: str
    api_version: str = "2024-11-30"
    operation_timeout_seconds: float = 180.0
    max_lines: int = 5000
    max_characters: int = 1_000_000
    max_response_bytes: int = 4_000_000

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("OCR endpoint MUST be an HTTPS origin")


class AzureDocumentIntelligenceOcr:
    """Call prebuilt-read with managed identity and bounded polling/output."""

    def __init__(
        self,
        *,
        config: AzureDocumentOcrConfig,
        credential: ManagedIdentityCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client

    def readiness(self) -> AdapterReadiness:
        """Report validated OCR composition without requesting an Azure token."""
        return configured_readiness("document-intelligence-ocr")

    async def probe_readiness(self) -> AdapterReadiness:
        """Authenticate and list at most one OCR model without analyzing content."""
        adapter = "document-intelligence-ocr"
        try:
            async with asyncio.timeout(5.0):
                token = await self._credential.get_token(_COGNITIVE_SCOPE)
                response = await self._client.get(
                    f"{self._config.endpoint.rstrip('/')}/documentintelligence/documentModels",
                    params={"api-version": self._config.api_version, "top": "1"},
                    headers={"Authorization": f"Bearer {token.token}"},
                )
                response.raise_for_status()
                if len(response.content) > self._config.max_response_bytes:
                    return live_unavailable_readiness(adapter, "probe_response_too_large")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        token = await self._credential.get_token(_COGNITIVE_SCOPE)
        url = (
            f"{self._config.endpoint.rstrip('/')}/documentintelligence/documentModels/"
            f"prebuilt-read:analyze?api-version={self._config.api_version}"
        )
        response = await self._client.post(
            url,
            content=content,
            headers={"Authorization": f"Bearer {token.token}", "Content-Type": version.media_type},
        )
        if response.status_code != 202:
            raise RuntimeError(f"OCR analyze request returned HTTP {response.status_code}")
        operation_url = response.headers.get("operation-location")
        if (
            not operation_url
            or urlparse(operation_url).hostname != urlparse(self._config.endpoint).hostname
        ):
            raise RuntimeError("OCR operation location is outside the configured origin")
        async with asyncio.timeout(self._config.operation_timeout_seconds):
            while True:
                result = await self._client.get(
                    operation_url,
                    headers={"Authorization": f"Bearer {token.token}"},
                )
                if len(result.content) > self._config.max_response_bytes:
                    raise RuntimeError("OCR response exceeded configured bounds")
                payload = result.json()
                status = payload.get("status")
                if status == "succeeded":
                    return _ocr_units(
                        payload,
                        self._config.max_lines,
                        self._config.max_characters,
                    )
                if status in {"failed", "canceled"}:
                    raise RuntimeError(f"OCR operation ended with status {status}")
                await asyncio.sleep(0.5)


class UnavailableImageOcr:
    """Fail closed when no OCR endpoint was configured for scanned content."""

    _REASON = "FDAI_OCR_ENDPOINT is not configured"

    def readiness(self) -> AdapterReadiness:
        return unavailable_readiness("document-intelligence-ocr", self._REASON)

    async def probe_readiness(self) -> AdapterReadiness:
        """Return the same explicit unavailability without external I/O."""
        return self.readiness()

    async def extract(
        self, *, version: DocumentVersion, content: bytes
    ) -> tuple[StructuralUnit, ...]:
        del version, content
        raise ProviderUnavailableError(self._REASON)


@dataclass(frozen=True, slots=True)
class AzureEmbeddingConfig:
    endpoint: str
    deployment: str
    api_version: str = "2024-06-01"
    dimension: int = 384


class EmbeddingModel(Protocol):
    """Generate fixed-dimensional vectors and expose live readiness."""

    def readiness(self) -> AdapterReadiness: ...

    async def probe_readiness(self) -> AdapterReadiness: ...

    async def embed(self, text: str) -> Sequence[float]: ...


class AzureEmbeddingModel:
    """Generate bounded embedding vectors with managed identity."""

    def __init__(
        self,
        *,
        config: AzureEmbeddingConfig,
        credential: ManagedIdentityCredential,
        client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._credential = credential
        self._client = client

    def readiness(self) -> AdapterReadiness:
        """Report validated embedding composition without requesting a token."""
        return configured_readiness("azure-openai-embedding")

    async def probe_readiness(self) -> AdapterReadiness:
        """Generate one fixed minimal vector within a short timeout."""
        adapter = "azure-openai-embedding"
        try:
            async with asyncio.timeout(5.0):
                await self.embed("readiness")
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def embed(self, text: str) -> Sequence[float]:
        token = await self._credential.get_token(_COGNITIVE_SCOPE)
        response = await self._client.post(
            f"{self._config.endpoint.rstrip('/')}/openai/deployments/"
            f"{self._config.deployment}/embeddings",
            params={"api-version": self._config.api_version},
            headers={"Authorization": f"Bearer {token.token}"},
            json={"input": text, "dimensions": self._config.dimension},
        )
        response.raise_for_status()
        try:
            vector = response.json()["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("embedding response is missing data[0].embedding") from exc
        if not isinstance(vector, list) or len(vector) != self._config.dimension:
            raise RuntimeError("embedding response dimension does not match configuration")
        return tuple(float(value) for value in vector)


class PgvectorDocumentIndex:
    """Atomically replace the chunks for one immutable document version."""

    def __init__(
        self,
        *,
        dsn: str,
        embedder: EmbeddingModel,
        dimension: int,
        max_chars: int = 1200,
        overlap: int = 150,
    ) -> None:
        self._dsn = dsn
        self._embedder = embedder
        self._dimension = dimension
        self._max_chars = max_chars
        self._overlap = overlap

    async def commit(self, envelope: DocumentEnvelope) -> int:
        rows: list[tuple[str, str, str, str, str, str]] = []
        doc_id = _document_ref(envelope.document_id, envelope.version_id)
        for unit in envelope.units:
            for index, text in enumerate(_chunks(unit.text, self._max_chars, self._overlap)):
                vector = await self._embedder.embed(text)
                chunk_id = f"{doc_id}:{unit.unit_id}:{index}"
                metadata = {
                    "governed_document": "true",
                    "document_id": str(envelope.document_id),
                    "version_id": str(envelope.version_id),
                    "collection_id": envelope.collection_id,
                    "access_descriptor_ref": envelope.access_descriptor_ref,
                    "locator": unit.locator,
                }
                rows.append(
                    (
                        chunk_id,
                        doc_id,
                        text,
                        f"document://{envelope.document_id}/versions/{envelope.version_id}#{unit.unit_id}",
                        _vector(vector, self._dimension),
                        json.dumps(metadata, sort_keys=True),
                    )
                )
        async with (
            await psycopg.AsyncConnection.connect(self._dsn) as connection,
            connection.transaction(),
        ):
            await connection.execute("DELETE FROM knowledge_chunk WHERE doc_id = %s", (doc_id,))
            for row in rows:
                await connection.execute(
                    "INSERT INTO knowledge_chunk "
                    "(chunk_id, doc_id, text, source_ref, embedding, metadata) "
                    "VALUES (%s, %s, %s, %s, %s::vector, %s::jsonb) "
                    "ON CONFLICT (chunk_id) DO UPDATE SET text=EXCLUDED.text, "
                    "source_ref=EXCLUDED.source_ref, embedding=EXCLUDED.embedding, "
                    "metadata=EXCLUDED.metadata",
                    row,
                )
        return len(rows)

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            await connection.execute(
                "DELETE FROM knowledge_chunk WHERE doc_id = %s",
                (_document_ref(document_id, version_id),),
            )


async def _read_bounded(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    content = bytearray()
    async for chunk in chunks:
        content.extend(chunk)
        if len(content) > limit:
            raise DocumentExtractionUnavailableError(ExtractionUnavailableReason.INPUT_BUDGET)
    return bytes(content)


def _text_units(text: str) -> tuple[StructuralUnit, ...]:
    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", text) if value.strip()]
    return tuple(
        StructuralUnit(
            unit_id=f"text-{index}", kind="paragraph", locator=f"paragraph:{index}", text=value
        )
        for index, value in enumerate(paragraphs, start=1)
    )


def _pdf_units(content: bytes) -> tuple[StructuralUnit, ...]:
    reader = pypdf.PdfReader(io.BytesIO(content))
    return tuple(
        StructuralUnit(unit_id=f"page-{index}", kind="page", locator=f"page:{index}", text=text)
        for index, page in enumerate(reader.pages, start=1)
        if (text := (page.extract_text() or "").strip())
    )


def _ocr_units(
    payload: dict[str, object], max_lines: int, max_chars: int
) -> tuple[StructuralUnit, ...]:
    result = payload.get("analyzeResult")
    pages = result.get("pages") if isinstance(result, dict) else None
    if not isinstance(pages, list):
        raise RuntimeError("OCR result has no pages")
    units: list[StructuralUnit] = []
    characters = 0
    for page_index, page in enumerate(pages, start=1):
        lines = page.get("lines") if isinstance(page, dict) else None
        if not isinstance(lines, list):
            raise RuntimeError("OCR page has no lines")
        for line_index, line in enumerate(lines, start=1):
            text = line.get("content") if isinstance(line, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            characters += len(text)
            if len(units) >= max_lines or characters > max_chars:
                raise RuntimeError("OCR output exceeded configured bounds")
            units.append(
                StructuralUnit(
                    unit_id=f"page-{page_index}-line-{line_index}",
                    kind="page",
                    locator=f"page:{page_index}:line:{line_index}",
                    text=text.strip(),
                )
            )
    return tuple(units)


def _looks_like_text(content: bytes) -> bool:
    sample = content[:4096]
    return b"\0" not in sample and (
        not sample
        or sum(value < 32 and value not in (9, 10, 13) for value in sample) / len(sample) < 0.02
    )


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


def _ooxml_media_type(suffix: str) -> str:
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[suffix]


def _chunks(text: str, max_chars: int, overlap: int) -> tuple[str, ...]:
    if not text:
        return ()
    values: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        values.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return tuple(values)


def _document_ref(document_id: UUID, version_id: UUID) -> str:
    return f"governed:{document_id}:{version_id}"


def _vector(values: Sequence[float], dimension: int) -> str:
    if len(values) != dimension:
        raise ValueError("embedding vector dimension mismatch")
    return "[" + ",".join(format(float(value), ".12g") for value in values) + "]"
