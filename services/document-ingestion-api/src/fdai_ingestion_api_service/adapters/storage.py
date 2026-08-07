"""ADLS Gen2 source storage owned by the Document Ingestion API."""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.filedatalake.aio import DataLakeServiceClient
from fdai_service_contracts import (
    DocumentNotFoundError,
    ProviderUnavailableError,
    StoredObjectInfo,
    UploadGrant,
    UploadSession,
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
    """Stream opaque upload keys into private ADLS without browser credentials."""

    def __init__(
        self,
        *,
        config: AzureDataLakeConfig,
        service_client: DataLakeServiceClient,
    ) -> None:
        self._config = config
        self._service = service_client
        self._files = service_client.get_file_system_client(config.source_file_system)
        self._derived = service_client.get_file_system_client(config.derived_file_system)

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        return UploadGrant(
            upload_id=session.upload_id,
            target=f"adls://{self._config.source_file_system}/{session.object_key}",
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
        file_client = self._files.get_file_client(object_key)
        digest = hashlib.sha256()
        observed_size = 0

        async def tracked() -> AsyncIterator[bytes]:
            nonlocal observed_size
            async for chunk in chunks:
                observed_size += len(chunk)
                if observed_size > max_size or observed_size > expected_size:
                    raise ValueError("streamed content exceeds the upload-session limit")
                digest.update(chunk)
                yield chunk

        try:
            await file_client.upload_data(
                tracked(),
                length=expected_size,
                overwrite=True,
                timeout=self._config.operation_timeout_seconds,
                max_concurrency=1,
            )
            if observed_size != expected_size:
                raise ValueError("streamed content size does not match the upload session")
            sha256 = digest.hexdigest()
            await file_client.set_metadata(
                {"fdai_sha256": sha256, "fdai_size": str(observed_size)},
                timeout=self._config.operation_timeout_seconds,
            )
            return StoredObjectInfo(object_key, observed_size, sha256)
        except Exception:
            try:
                await file_client.delete_file(timeout=self._config.operation_timeout_seconds)
            except ResourceNotFoundError:
                pass
            raise

    async def stat(self, object_key: str) -> StoredObjectInfo:
        try:
            properties = await self._files.get_file_client(object_key).get_file_properties(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError("source object was not found") from exc
        metadata = properties.metadata or {}
        sha256 = metadata.get("fdai_sha256")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ProviderUnavailableError("source object hash metadata is unavailable")
        return StoredObjectInfo(object_key, int(properties.size), sha256)

    async def read(self, object_key: str) -> AsyncIterator[bytes]:
        try:
            download = await self._files.get_file_client(object_key).download_file(
                timeout=self._config.operation_timeout_seconds
            )
            async for chunk in download.chunks():
                yield chunk
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError("source object was not found") from exc

    async def revoke_upload(self, upload_id: UUID) -> None:
        return None

    async def delete(self, object_key: str) -> None:
        try:
            await self._files.get_file_client(object_key).delete_file(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

    async def delete_artifact(self, document_id: UUID, version_id: UUID) -> None:
        path = f"documents/{document_id.hex}/versions/{version_id.hex}/envelope.json"
        try:
            await self._derived.get_file_client(path).delete_file(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

    async def close(self) -> None:
        await self._service.close()
