"""Durable local adapters for the independent Document Ingestion API."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from uuid import UUID

from aiokafka import AIOKafkaProducer
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentNotFoundError,
    StoredObjectInfo,
    UploadGrant,
    UploadSession,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)


class LocalDocumentObjectStore:
    """Persist opaque source and derived object keys under one private local root."""

    def __init__(self, root: Path, *, chunk_size: int = 64 * 1024) -> None:
        self._root = root.resolve()
        self._source = self._root / "source"
        self._derived = self._root / "derived"
        self._source.mkdir(parents=True, exist_ok=True)
        self._derived.mkdir(parents=True, exist_ok=True)
        self._chunk_size = chunk_size

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("local-document-storage")

    async def probe_readiness(self) -> AdapterReadiness:
        try:
            await asyncio.to_thread(self._source.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(self._derived.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            return live_unavailable_readiness(
                "local-document-storage", f"probe_failed:{type(exc).__name__}"
            )
        return live_readiness("local-document-storage")

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(
            upload_id=session.upload_id,
            target=f"local://source/{session.object_key}",
            expires_at=session.expires_at,
        )

    async def resume_upload(self, session: UploadSession) -> UploadGrant:
        return await self.issue_upload(session)

    async def put_stream(
        self,
        object_key: str,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int,
        max_size: int,
    ) -> StoredObjectInfo:
        path = self._path(self._source, object_key)
        temporary = path.with_suffix(f"{path.suffix}.partial")
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        observed_size = 0
        handle = await asyncio.to_thread(temporary.open, "wb")
        try:
            async for chunk in chunks:
                observed_size += len(chunk)
                if observed_size > expected_size or observed_size > max_size:
                    raise ValueError("streamed content exceeds the upload-session limit")
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
            if observed_size != expected_size:
                raise ValueError("streamed content size does not match the upload session")
            await asyncio.to_thread(handle.flush)
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temporary.replace, path)
        except BaseException:
            if not handle.closed:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            raise
        return StoredObjectInfo(object_key, observed_size, digest.hexdigest())

    async def stat(self, object_key: str) -> StoredObjectInfo:
        path = self._path(self._source, object_key)
        if not path.is_file():
            raise DocumentNotFoundError("source object was not found")
        return await asyncio.to_thread(_stat_file, path, object_key)

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        path = self._path(self._source, object_key)
        if not path.is_file():
            raise DocumentNotFoundError("source object was not found")
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, self._chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def revoke_upload(self, upload_id: UUID) -> None:
        return None

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._path(self._source, object_key).unlink, missing_ok=True)

    async def delete_artifact(self, document_id: UUID, version_id: UUID) -> None:
        path = self._derived / "documents" / document_id.hex / "versions" / version_id.hex
        await asyncio.to_thread((path / "envelope.json").unlink, missing_ok=True)

    async def close(self) -> None:
        return None

    @staticmethod
    def _path(root: Path, object_key: str) -> Path:
        path = (root / object_key).resolve()
        if not path.is_relative_to(root):
            raise ValueError("object key escapes the configured storage root")
        return path


class DeterministicLocalEmbeddingModel:
    """Generate stable local vectors without claiming external model evidence."""

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


class PlaintextKafkaPublisher:
    """Publish idempotent local records to a loopback plaintext Kafka broker."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str = "fdai-ingestion-api-local",
    ) -> None:
        if not bootstrap_servers:
            raise ValueError("Kafka bootstrap servers MUST NOT be empty")
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._producer: AIOKafkaProducer | None = None
        self._lock = asyncio.Lock()

    def readiness(self) -> AdapterReadiness:
        return configured_readiness("plaintext-kafka-publisher")

    async def probe_readiness(self) -> AdapterReadiness:
        try:
            producer = await asyncio.wait_for(self._get_producer(), timeout=5.0)
            await asyncio.wait_for(producer.client.fetch_all_metadata(), timeout=5.0)
        except Exception as exc:  # noqa: BLE001 - expose only the safe exception type
            return live_unavailable_readiness(
                "plaintext-kafka-publisher", f"probe_failed:{type(exc).__name__}"
            )
        return live_readiness("plaintext-kafka-publisher")

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> object:
        return await (await self._get_producer()).send_and_wait(
            topic,
            key=key.encode("utf-8"),
            value=json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode(),
        )

    async def close(self) -> None:
        async with self._lock:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

    async def _get_producer(self) -> AIOKafkaProducer:
        async with self._lock:
            if self._producer is None:
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._bootstrap_servers,
                    client_id=self._client_id,
                    security_protocol="PLAINTEXT",
                    api_version="2.0.0",
                    enable_idempotence=True,
                    acks="all",
                )
                try:
                    await producer.start()
                except BaseException:
                    await producer.stop()
                    raise
                self._producer = producer
            return self._producer


def _stat_file(path: Path, object_key: str) -> StoredObjectInfo:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return StoredObjectInfo(object_key, size, digest.hexdigest())


__all__ = [
    "DeterministicLocalEmbeddingModel",
    "LocalDocumentObjectStore",
    "PlaintextKafkaPublisher",
]
