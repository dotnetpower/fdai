"""ADLS Gen2 source storage owned by the Document Ingestion API."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.filedatalake.aio import DataLakeLeaseClient, DataLakeServiceClient
from fdai_service_contracts import (
    AdapterReadiness,
    DocumentNotFoundError,
    ProviderUnavailableError,
    StoredObjectInfo,
    UploadGrant,
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
    lease_duration_seconds: int = 60

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
        if not 15 <= self.lease_duration_seconds <= 60:
            raise ValueError("ADLS lease duration MUST be in [15, 60] seconds")


class AzureDataLakeObjectStore:
    """Stream opaque upload keys into private ADLS without browser credentials."""

    def __init__(
        self,
        *,
        config: AzureDataLakeConfig,
        service_client: DataLakeServiceClient,
        lease_client_factory: type[DataLakeLeaseClient] = DataLakeLeaseClient,
    ) -> None:
        self._config = config
        self._service = service_client
        self._files = service_client.get_file_system_client(config.source_file_system)
        self._derived = service_client.get_file_system_client(config.derived_file_system)
        self._lease_client_factory = lease_client_factory

    def readiness(self) -> AdapterReadiness:
        """Report validated composition without performing an ADLS request."""
        return configured_readiness("adls-source")

    async def probe_readiness(self) -> AdapterReadiness:
        """Read source and derived file-system properties within a short timeout."""
        adapter = "adls-source"
        try:
            async with asyncio.timeout(min(float(self._config.operation_timeout_seconds), 5.0)):
                await self._files.get_file_system_properties(
                    timeout=min(self._config.operation_timeout_seconds, 5)
                )
                await self._derived.get_file_system_properties(
                    timeout=min(self._config.operation_timeout_seconds, 5)
                )
        except TimeoutError:
            return live_unavailable_readiness(adapter, "probe_timeout")
        except Exception as exc:  # noqa: BLE001 - return only the safe exception type
            return live_unavailable_readiness(adapter, f"probe_failed:{type(exc).__name__}")
        return live_readiness(adapter)

    async def issue_upload(self, session: UploadSession) -> UploadGrant:
        completed_parts = await self._completed_parts(session.object_key)
        return UploadGrant(
            upload_id=session.upload_id,
            target=f"adls://{self._config.source_file_system}/{session.object_key}",
            expires_at=session.expires_at,
            completed_parts=completed_parts,
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
        try:
            await file_client.get_file_properties(timeout=self._config.operation_timeout_seconds)
        except ResourceNotFoundError:
            try:
                await file_client.create_file(timeout=self._config.operation_timeout_seconds)
            except ResourceExistsError:
                pass
        lease = self._lease_client_factory(file_client)
        await lease.acquire(lease_duration=self._config.lease_duration_seconds)
        deleted_under_lease = False
        try:
            properties = await file_client.get_file_properties(
                lease=lease,
                timeout=self._config.operation_timeout_seconds,
            )
            metadata = properties.metadata or {}
            if (
                metadata.get("fdai_upload_state") == "complete"
                and int(properties.size) == expected_size
                and isinstance(metadata.get("fdai_sha256"), str)
            ):
                return StoredObjectInfo(object_key, expected_size, metadata["fdai_sha256"])
            existing = await self._read_existing(file_client, lease=lease, max_size=max_size)
            if len(existing) > expected_size:
                await self._delete_partial(file_client, lease=lease)
                raise ValueError("stored upload prefix exceeds the upload-session size")

            digest = hashlib.sha256()
            digest.update(existing)
            observed_size = 0
            offset = len(existing)
            compared = 0
            async for chunk in chunks:
                if not chunk:
                    continue
                observed_size += len(chunk)
                if observed_size > max_size or observed_size > expected_size:
                    raise ValueError("streamed content exceeds the upload-session limit")
                prefix_count = min(len(chunk), len(existing) - compared)
                if (
                    prefix_count
                    and chunk[:prefix_count] != existing[compared : compared + prefix_count]
                ):
                    raise ValueError("streamed content does not match the stored upload prefix")
                compared += prefix_count
                suffix = chunk[prefix_count:]
                if suffix:
                    await lease.renew()
                    await file_client.append_data(
                        suffix,
                        offset=offset,
                        length=len(suffix),
                        lease=lease,
                        timeout=self._config.operation_timeout_seconds,
                    )
                    offset += len(suffix)
                    digest.update(suffix)
                    await file_client.flush_data(
                        offset,
                        close=False,
                        lease=lease,
                        timeout=self._config.operation_timeout_seconds,
                    )
            if observed_size != expected_size or compared != len(existing):
                raise ValueError("streamed content size does not match the upload session")
            sha256 = digest.hexdigest()
            await file_client.set_metadata(
                {
                    "fdai_sha256": sha256,
                    "fdai_size": str(offset),
                    "fdai_upload_state": "complete",
                },
                lease=lease,
                timeout=self._config.operation_timeout_seconds,
            )
            return StoredObjectInfo(object_key, offset, sha256)
        except ValueError:
            await self._delete_partial(file_client, lease=lease)
            deleted_under_lease = True
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep a flushed prefix so the same bounded upload can resume after a transient failure.
            raise
        finally:
            if not deleted_under_lease:
                await lease.release()

    async def cleanup_orphans(self, *, older_than: datetime, limit: int = 100) -> int:
        if limit < 1 or limit > 1000:
            raise ValueError("orphan cleanup limit MUST be in [1, 1000]")
        deleted = 0
        async for path in self._files.get_paths(path="quarantine", recursive=True):
            if deleted >= limit:
                break
            if getattr(path, "is_directory", False):
                continue
            last_modified = getattr(path, "last_modified", None)
            if not isinstance(last_modified, datetime) or last_modified >= older_than:
                continue
            client = self._files.get_file_client(path.name)
            try:
                properties = await client.get_file_properties(
                    timeout=self._config.operation_timeout_seconds
                )
            except ResourceNotFoundError:
                continue
            if (properties.metadata or {}).get("fdai_upload_state") == "complete":
                continue
            await self._delete_partial(client)
            deleted += 1
        return deleted

    async def _completed_parts(self, object_key: str) -> tuple[str, ...]:
        try:
            properties = await self._files.get_file_client(object_key).get_file_properties(
                timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return ()
        size = int(properties.size)
        return (f"bytes=0-{size - 1}",) if size > 0 else ()

    async def _read_existing(
        self, file_client: object, *, lease: DataLakeLeaseClient, max_size: int
    ) -> bytes:
        download = await file_client.download_file(  # type: ignore[attr-defined]
            lease=lease, timeout=self._config.operation_timeout_seconds
        )
        content = bytearray()
        async for chunk in download.chunks():
            content.extend(chunk)
            if len(content) > max_size:
                raise ValueError("stored upload prefix exceeds the configured limit")
        return bytes(content)

    async def _delete_partial(
        self, file_client: object, *, lease: DataLakeLeaseClient | None = None
    ) -> None:
        try:
            await file_client.delete_file(  # type: ignore[attr-defined]
                lease=lease, timeout=self._config.operation_timeout_seconds
            )
        except ResourceNotFoundError:
            return

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
