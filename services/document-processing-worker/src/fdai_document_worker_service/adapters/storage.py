"""ADLS Gen2 source and derived-artifact adapters owned by the worker."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentEnvelope,
    DocumentNotFoundError,
    UploadSession,
    configured_readiness,
    live_readiness,
    live_unavailable_readiness,
)

_FILESYSTEM_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?")


@dataclass(frozen=True, slots=True)
class AzureDataLakeConfig:
    account_url: str
    source_file_system: str = "documents"
    derived_file_system: str = "derived"
    operation_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.account_url.startswith("https://"):
            raise ValueError("ADLS HTTPS account_url is required")
        if not all(
            _FILESYSTEM_RE.fullmatch(name)
            for name in (self.source_file_system, self.derived_file_system)
        ):
            raise ValueError("ADLS file-system names MUST be lowercase container names")
        if self.operation_timeout_seconds < 1:
            raise ValueError("ADLS operation timeout MUST be positive")


class AzureDataLakeObjectStore:
    """Read, promote, and delete opaque source objects without upload grants."""

    def __init__(
        self,
        *,
        config: AzureDataLakeConfig,
        service_client: DataLakeServiceClient,
    ) -> None:
        self._config = config
        self._service = service_client
        self._files = service_client.get_file_system_client(config.source_file_system)

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        try:
            download = await self._files.get_file_client(object_key).download_file(
                timeout=self._config.operation_timeout_seconds
            )
            async for chunk in download.chunks():
                yield chunk
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError("source object was not found") from exc

    def readiness(self) -> AdapterReadiness:
        """Report validated composition without performing an ADLS request."""
        return configured_readiness("adls-source")

    async def probe_readiness(self) -> AdapterReadiness:
        """Read source file-system properties within a short timeout."""
        return await _probe_file_system(self._files, "adls-source", self._config)

    async def delete(self, object_key: str) -> None:
        try:
            await self._files.get_file_client(object_key).delete_file(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

    async def promote(self, session: UploadSession) -> str:
        if session.object_key.startswith("governed/"):
            return session.object_key
        target = self.governed_key(session)
        await self._ensure_parent_directories(target)
        source = self._files.get_file_client(session.object_key)
        try:
            await source.rename_file(
                f"{self._config.source_file_system}/{target}",
                timeout=self._config.operation_timeout_seconds,
            )
        except ResourceNotFoundError as exc:
            try:
                await self._files.get_file_client(target).get_file_properties(
                    timeout=self._config.operation_timeout_seconds
                )
            except ResourceNotFoundError:
                raise DocumentNotFoundError("source object was not found during promotion") from exc
        return target

    async def _ensure_parent_directories(self, target: str) -> None:
        parts = target.rsplit("/", 1)[0].split("/")
        for index in range(1, len(parts) + 1):
            try:
                await self._files.create_directory(
                    "/".join(parts[:index]),
                    timeout=self._config.operation_timeout_seconds,
                )
            except ResourceExistsError:
                continue

    @staticmethod
    def governed_key(session: UploadSession) -> str:
        collection = hashlib.sha256(session.collection_id.encode()).hexdigest()[:16]
        return f"governed/{collection}/{session.document_id.hex}/{session.version_id.hex}/source"

    async def close(self) -> None:
        await self._service.close()


class AzureDataLakeArtifactStore:
    """Persist canonical document envelopes in the private derived filesystem."""

    def __init__(
        self,
        *,
        config: AzureDataLakeConfig,
        service_client: DataLakeServiceClient,
    ) -> None:
        self._config = config
        self._service = service_client
        self._files = service_client.get_file_system_client(config.derived_file_system)

    async def put(self, envelope: DocumentEnvelope) -> str:
        path = self._path(envelope.document_id, envelope.version_id)
        payload = envelope.model_dump_json().encode()
        await self._files.get_file_client(path).upload_data(
            payload,
            length=len(payload),
            overwrite=True,
            metadata={
                "fdai_document_id": envelope.document_id.hex,
                "fdai_version_id": envelope.version_id.hex,
                "fdai_source_sha256": envelope.source_sha256,
            },
            timeout=self._config.operation_timeout_seconds,
        )
        return f"{self._config.account_url}/{self._config.derived_file_system}/{path}"

    def readiness(self) -> AdapterReadiness:
        """Report validated composition without performing an ADLS request."""
        return configured_readiness("adls-artifact")

    async def probe_readiness(self) -> AdapterReadiness:
        """Read derived file-system properties within a short timeout."""
        return await _probe_file_system(self._files, "adls-artifact", self._config)

    async def delete(self, document_id: UUID, version_id: UUID) -> None:
        try:
            await self._files.get_file_client(self._path(document_id, version_id)).delete_file(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

    async def close(self) -> None:
        await self._service.close()

    @staticmethod
    def _path(document_id: UUID, version_id: UUID) -> str:
        return f"documents/{document_id.hex}/versions/{version_id.hex}/envelope.json"


async def _probe_file_system(
    file_system: object,
    adapter: str,
    config: AzureDataLakeConfig,
) -> AdapterReadiness:
    try:
        async with asyncio.timeout(min(float(config.operation_timeout_seconds), 5.0)):
            await file_system.get_file_system_properties(  # type: ignore[attr-defined]
                timeout=min(config.operation_timeout_seconds, 5)
            )
    except TimeoutError:
        return live_unavailable_readiness(adapter, "probe_timeout")
    except Exception as exc:  # noqa: BLE001 - return only the safe exception type
        return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
    return live_readiness(adapter)
