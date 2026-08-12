"""Durable local adapters for the independent Document Processing Worker."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from uuid import UUID

from fdai_service_contracts import (
    AdapterReadiness,
    DocumentEnvelope,
    DocumentNotFoundError,
    UploadSession,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)


class LocalDocumentObjectStore:
    """Read and promote opaque source objects under one private local root."""

    def __init__(self, root: Path, *, chunk_size: int = 64 * 1024) -> None:
        self._source = root.resolve() / "source"
        self._source.mkdir(parents=True, exist_ok=True)
        self._chunk_size = chunk_size

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("local-document-source")

    async def probe_readiness(self) -> AdapterReadiness:
        try:
            await asyncio.to_thread(self._source.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            return live_unavailable_readiness(
                "local-document-source", f"probe_failed:{type(exc).__name__}"
            )
        return live_readiness("local-document-source")

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

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._path(object_key).unlink, missing_ok=True)

    async def promote(self, session: UploadSession) -> str:
        if session.object_key.startswith("governed/"):
            return session.object_key
        target = self.governed_key(session)
        source = self._path(session.object_key)
        destination = self._path(target)
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        if source.is_file():
            await asyncio.to_thread(source.replace, destination)
        elif not destination.is_file():
            raise DocumentNotFoundError("source object was not found during promotion")
        return target

    @staticmethod
    def governed_key(session: UploadSession) -> str:
        collection = hashlib.sha256(session.collection_id.encode()).hexdigest()[:16]
        return f"governed/{collection}/{session.document_id.hex}/{session.version_id.hex}/source"

    async def close(self) -> None:
        return None

    def _path(self, object_key: str) -> Path:
        path = (self._source / object_key).resolve()
        if not path.is_relative_to(self._source):
            raise ValueError("object key escapes the configured storage root")
        return path


class LocalDocumentArtifactStore:
    """Persist canonical document envelopes under the shared local root."""

    def __init__(self, root: Path) -> None:
        self._derived = root.resolve() / "derived"
        self._derived.mkdir(parents=True, exist_ok=True)

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("local-document-artifact")

    async def probe_readiness(self) -> AdapterReadiness:
        try:
            await asyncio.to_thread(self._derived.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            return live_unavailable_readiness(
                "local-document-artifact", f"probe_failed:{type(exc).__name__}"
            )
        return live_readiness("local-document-artifact")

    async def put(self, envelope: DocumentEnvelope) -> str:
        path = self._path(envelope.document_id, envelope.version_id)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, envelope.model_dump_json(), encoding="utf-8")
        return f"local://derived/{path.relative_to(self._derived).as_posix()}"

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        await asyncio.to_thread(self._path(document_id, version_id).unlink, missing_ok=True)

    async def close(self) -> None:
        return None

    def _path(self, document_id: UUID, version_id: UUID) -> Path:
        return (
            self._derived
            / "documents"
            / document_id.hex
            / "versions"
            / version_id.hex
            / "envelope.json"
        )


class DeterministicLocalEmbeddingModel:
    """Generate the same stable local vectors used by the local ingestion API."""

    def __init__(self, *, dimension: int = 384) -> None:
        if dimension < 1:
            raise ValueError("embedding dimension MUST be positive")
        self._dimension = dimension

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("deterministic-local-embedding")

    async def probe_readiness(self) -> AdapterReadiness:
        return live_readiness("deterministic-local-embedding")

    async def embed(self, text: str) -> Sequence[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return tuple(
            (digest[index % len(digest)] - 127.5) / 127.5 for index in range(self._dimension)
        )


__all__ = [
    "DeterministicLocalEmbeddingModel",
    "LocalDocumentArtifactStore",
    "LocalDocumentObjectStore",
]
