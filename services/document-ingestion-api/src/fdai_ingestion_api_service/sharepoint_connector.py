"""FDAI-native cross-tenant SharePoint connector intake."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import (
    DocumentNotFoundError,
    DocumentPurpose,
    DocumentState,
    SourceStorageMode,
    UploadSession,
    classify_document_intake,
)

from fdai_ingestion_api_service.adapters.sharepoint import (
    SharePointDeltaItem,
    SharePointRevisionSupersededError,
)
from fdai_ingestion_api_service.adapters.sharepoint_state import (
    ConnectorBindingConflictError,
    ConnectorDocumentBinding,
)
from fdai_ingestion_api_service.ingestion import CreateUploadRequest, DocumentIngestionService


class SharePointConnectorState(Protocol):
    async def get_binding(
        self, *, connector_id: str, source_item_id: str
    ) -> ConnectorDocumentBinding | None: ...

    async def event_matches(
        self,
        *,
        connector_id: str,
        source_item_id: str,
        source_revision: str,
        source_sequence: int,
        source_name: str | None,
        size_bytes: int,
        content_sha256: str | None,
        deleted: bool,
    ) -> bool: ...

    async def apply_batch(
        self,
        *,
        connector_id: str,
        collection_id: str,
        access_descriptor_ref: str,
        idempotency_key: str,
        items: tuple[SharePointDeltaItem, ...],
    ) -> None: ...

    async def bind_document(
        self,
        *,
        connector_id: str,
        source_item_id: str,
        document_id: UUID,
        version_id: UUID,
        source_revision: str,
        source_sequence: int,
    ) -> None: ...

    async def pending_cancellations(
        self, *, connector_id: str, source_item_id: str
    ) -> tuple[str, ...]: ...

    async def pending_cancellation_items(
        self, *, connector_id: str, limit: int
    ) -> tuple[str, ...]: ...

    async def complete_cancellation(
        self, *, connector_id: str, source_item_id: str, source_revision: str
    ) -> None: ...

    async def queue_cancellation(
        self, *, connector_id: str, source_item_id: str, source_revision: str
    ) -> None: ...

    async def record_rejection(
        self,
        *,
        connector_id: str,
        source_item_id: str,
        source_revision: str,
        source_sequence: int,
        failure_code: str,
    ) -> None: ...

    async def finalize_resync(self, *, connector_id: str, sync_epoch: int, limit: int) -> bool: ...


class ConnectorDeletionService(Protocol):
    async def delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> object: ...


class SharePointContentSource(Protocol):
    async def download(
        self,
        source_item_id: str,
        *,
        source_revision: str,
        expected_size: int,
        max_size: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SharePointConnectorConfig:
    connector_id: str
    target_tenant_id: str
    collection_id: str
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    purposes: tuple[DocumentPurpose, ...] = (DocumentPurpose.KNOWLEDGE_BASE,)

    def __post_init__(self) -> None:
        values = (
            self.connector_id,
            self.target_tenant_id,
            self.collection_id,
            self.access_descriptor_ref,
            self.retention_policy_version,
        )
        if any(not value or len(value) > 512 for value in values):
            raise ValueError("SharePoint connector policy values MUST be non-empty and bounded")
        try:
            UUID(self.target_tenant_id)
        except ValueError as exc:
            raise ValueError("SharePoint target tenant MUST be a UUID") from exc
        if not self.purposes:
            raise ValueError("SharePoint connector purposes MUST NOT be empty")

    @property
    def binding_id(self) -> str:
        tenant_digest = hashlib.sha256(self.target_tenant_id.encode()).hexdigest()[:16]
        return f"{self.connector_id}:{tenant_digest}:native-v1"


class SharePointConnectorIntake:
    """Import connector-fetched SharePoint bytes with deterministic retry identities."""

    def __init__(
        self,
        *,
        config: SharePointConnectorConfig,
        service: DocumentIngestionService,
        state: SharePointConnectorState,
        deletion: ConnectorDeletionService | None = None,
    ) -> None:
        self._config = config
        self._service = service
        self._state = state
        self._deletion = deletion

    @property
    def connector_id(self) -> str:
        return self._config.connector_id

    def policy_rejection(
        self,
        *,
        source_name: str | None,
        media_type: str,
        size_bytes: int,
    ) -> str | None:
        if source_name is None:
            return "source_name_missing"
        if size_bytes > self._service.capabilities.max_file_size:
            return "source_too_large"
        try:
            source_format = classify_document_intake(source_name, media_type)
        except ValueError:
            return "unsupported_format"
        if source_format.format_id not in self._service.capabilities.supported_formats:
            return "unsupported_format"
        return None

    async def record_rejection(
        self,
        *,
        item: SharePointDeltaItem,
        source_sequence: int,
        failure_code: str,
    ) -> None:
        rejected = replace(item, source_sequence=source_sequence)
        await self._state.apply_batch(
            connector_id=self._config.binding_id,
            collection_id=self._config.collection_id,
            access_descriptor_ref=self._config.access_descriptor_ref,
            idempotency_key=(
                f"sharepoint-connector:{self._config.binding_id}:"
                f"{item.source_item_id}:{item.source_revision}:{source_sequence}"
            ),
            items=(rejected,),
        )
        await self._state.record_rejection(
            connector_id=self._config.binding_id,
            source_item_id=item.source_item_id,
            source_revision=item.source_revision,
            source_sequence=source_sequence,
            failure_code=failure_code,
        )

    async def finalize_resync(self, *, sync_epoch: int, limit: int) -> bool:
        return await self._state.finalize_resync(
            connector_id=self._config.binding_id,
            sync_epoch=sync_epoch,
            limit=limit,
        )

    async def ingest(
        self,
        *,
        actor_id: str,
        source_item_id: str,
        source_revision: str,
        source_name: str,
        media_type: str,
        content: bytes,
        source_sequence: int,
        sync_epoch: int = 0,
    ) -> UploadSession:
        _bounded(source_item_id, "source_item_id")
        _bounded(source_revision, "source_revision")
        _bounded(source_name, "source_name")
        _sequence(source_sequence)
        digest = hashlib.sha256(content).hexdigest()
        document_id = _stable_uuid(f"{self._config.binding_id}:document:{source_item_id}")
        version_id = _stable_uuid(
            f"{self._config.binding_id}:version:{source_item_id}:{source_revision}"
        )
        upload_id = _stable_uuid(
            f"{self._config.binding_id}:upload:{source_item_id}:{source_revision}"
        )
        binding = await self._state.get_binding(
            connector_id=self._config.binding_id,
            source_item_id=source_item_id,
        )
        if binding is not None and binding.document_id != document_id:
            raise RuntimeError("connector item document identity changed")
        idempotency_key = (
            f"sharepoint-connector:{self._config.binding_id}:"
            f"{source_item_id}:{source_revision}:{source_sequence}"
        )
        await self._state.apply_batch(
            connector_id=self._config.binding_id,
            collection_id=self._config.collection_id,
            access_descriptor_ref=self._config.access_descriptor_ref,
            idempotency_key=idempotency_key,
            items=(
                SharePointDeltaItem(
                    source_item_id=source_item_id,
                    source_revision=source_revision,
                    source_name=source_name,
                    size_bytes=len(content),
                    content_sha256=digest,
                    deleted=False,
                    source_sequence=source_sequence,
                    sync_epoch=sync_epoch,
                ),
            ),
        )
        if (
            await self._state.event_matches(
                connector_id=self._config.binding_id,
                source_item_id=source_item_id,
                source_revision=source_revision,
                source_sequence=source_sequence,
                source_name=source_name,
                size_bytes=len(content),
                content_sha256=digest,
                deleted=False,
            )
            is False
        ):
            raise RuntimeError("connector source event was superseded")
        try:
            session = await self._service.get_upload(
                actor_id=actor_id,
                actor_groups=frozenset({"role:Owner"}),
                upload_id=upload_id,
            )
            _validate_retry(session, digest=digest, size=len(content), version_id=version_id)
        except DocumentNotFoundError:
            request = CreateUploadRequest(
                source_name=source_name,
                collection_id=self._config.collection_id,
                media_type_hint=media_type,
                expected_size=len(content),
                expected_sha256=digest,
                storage_mode=SourceStorageMode.MANAGED_COPY,
                purposes=self._config.purposes,
                access_descriptor_ref=self._config.access_descriptor_ref,
                reader_groups=self._config.reader_groups,
                retention_policy_version=self._config.retention_policy_version,
                document_id=document_id,
                supersedes_version_id=(binding.version_id if binding is not None else None),
                upload_id=upload_id,
                version_id=version_id,
                connector_idempotency_key=idempotency_key,
            )
            try:
                session, _grant = await self._service.create_upload(
                    actor_id=actor_id,
                    actor_groups=frozenset({"role:Owner"}),
                    request=request,
                )
            except ValueError as exc:
                if str(exc) != "document upload or version already exists":
                    raise
                session = await self._service.get_upload(
                    actor_id=actor_id,
                    actor_groups=frozenset({"role:Owner"}),
                    upload_id=upload_id,
                )
                _validate_retry(session, digest=digest, size=len(content), version_id=version_id)
        try:
            await self._state.bind_document(
                connector_id=self._config.binding_id,
                source_item_id=source_item_id,
                document_id=document_id,
                version_id=version_id,
                source_revision=source_revision,
                source_sequence=source_sequence,
            )
        except ConnectorBindingConflictError:
            await self._state.queue_cancellation(
                connector_id=self._config.binding_id,
                source_item_id=source_item_id,
                source_revision=source_revision,
            )
            await self._drain_cancellations(
                actor_id=actor_id,
                source_item_id=source_item_id,
            )
            raise
        await self._drain_cancellations(
            actor_id=actor_id,
            source_item_id=source_item_id,
        )
        if session.state is DocumentState.CREATED:
            await self._service.resume_upload(
                actor_id=actor_id,
                actor_groups=frozenset({"role:Owner"}),
                upload_id=upload_id,
            )
            session = await self._service.get_upload(
                actor_id=actor_id,
                actor_groups=frozenset({"role:Owner"}),
                upload_id=upload_id,
            )
        if session.state is DocumentState.UPLOADING:
            await self._service.put_streaming_content(
                actor_id=actor_id,
                actor_groups=frozenset({"role:Owner"}),
                upload_id=upload_id,
                chunks=_one_chunk(content),
            )
            session = await self._service.complete_upload(
                actor_id=actor_id,
                actor_groups=frozenset({"role:Owner"}),
                upload_id=upload_id,
            )
        return session

    async def _drain_cancellations(self, *, actor_id: str, source_item_id: str) -> None:
        for pending_revision in await self._state.pending_cancellations(
            connector_id=self._config.binding_id, source_item_id=source_item_id
        ):
            prior_upload_id = _stable_uuid(
                f"{self._config.binding_id}:upload:{source_item_id}:{pending_revision}"
            )
            try:
                prior = await self._service.get_upload(
                    actor_id=actor_id,
                    actor_groups=frozenset({"role:Owner"}),
                    upload_id=prior_upload_id,
                )
            except DocumentNotFoundError:
                prior = None
            if prior is not None:
                if prior.state in {
                    DocumentState.CREATED,
                    DocumentState.UPLOADING,
                    DocumentState.RECEIVED,
                }:
                    await self._service.cancel_upload(
                        actor_id=actor_id,
                        actor_groups=frozenset({"role:Owner"}),
                        upload_id=prior_upload_id,
                    )
                elif prior.state not in {
                    DocumentState.DELETING,
                    DocumentState.DELETED,
                }:
                    if self._deletion is None:
                        raise RuntimeError("connector lineage deletion service is unavailable")
                    await self._deletion.delete(
                        actor_id=actor_id,
                        actor_groups=frozenset({"role:Owner"}),
                        document_id=prior.document_id,
                        version_id=prior.version_id,
                    )
            await self._state.complete_cancellation(
                connector_id=self._config.binding_id,
                source_item_id=source_item_id,
                source_revision=pending_revision,
            )

    async def reconcile_cancellations(self, *, actor_id: str, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("connector cancellation item limit MUST be in [1, 1000]")
        items = await self._state.pending_cancellation_items(
            connector_id=self._config.binding_id,
            limit=limit,
        )
        for source_item_id in items:
            await self._drain_cancellations(
                actor_id=actor_id,
                source_item_id=source_item_id,
            )
        return len(items)

    async def delete(
        self,
        *,
        actor_id: str,
        source_item_id: str,
        source_revision: str,
        source_sequence: int,
        sync_epoch: int = 0,
    ) -> None:
        _bounded(source_item_id, "source_item_id")
        _bounded(source_revision, "source_revision")
        _sequence(source_sequence)
        await self._state.apply_batch(
            connector_id=self._config.binding_id,
            collection_id=self._config.collection_id,
            access_descriptor_ref=self._config.access_descriptor_ref,
            idempotency_key=(
                f"sharepoint-connector:{self._config.binding_id}:"
                f"{source_item_id}:{source_revision}:{source_sequence}:deleted"
            ),
            items=(
                SharePointDeltaItem(
                    source_item_id=source_item_id,
                    source_revision=source_revision,
                    source_name=None,
                    size_bytes=0,
                    content_sha256=None,
                    deleted=True,
                    source_sequence=source_sequence,
                    sync_epoch=sync_epoch,
                ),
            ),
        )
        if (
            await self._state.event_matches(
                connector_id=self._config.binding_id,
                source_item_id=source_item_id,
                source_revision=source_revision,
                source_sequence=source_sequence,
                source_name=None,
                size_bytes=0,
                content_sha256=None,
                deleted=True,
            )
            is False
        ):
            raise RuntimeError("connector deletion event was superseded")
        await self._drain_cancellations(
            actor_id=actor_id,
            source_item_id=source_item_id,
        )


class NativeSharePointDeltaSink:
    """Download delta items and pass them through the governed intake lifecycle."""

    def __init__(
        self,
        *,
        config: SharePointConnectorConfig,
        source: SharePointContentSource,
        intake: SharePointConnectorIntake,
        max_file_size: int,
    ) -> None:
        if max_file_size < 1:
            raise ValueError("SharePoint connector file-size limit MUST be positive")
        self._config = config
        self._source = source
        self._intake = intake
        self._max_file_size = max_file_size

    async def apply_batch(
        self,
        *,
        connector_id: str,
        collection_id: str,
        access_descriptor_ref: str,
        idempotency_key: str,
        sync_epoch: int,
        items: Sequence[SharePointDeltaItem],
    ) -> None:
        if (
            connector_id != self._config.connector_id
            or collection_id != self._config.collection_id
            or access_descriptor_ref != self._config.access_descriptor_ref
        ):
            raise RuntimeError("SharePoint connector batch policy binding changed")
        sequence = _batch_sequence(idempotency_key, connector_id)
        actor_id = f"sharepoint-connector:{self._config.binding_id}:reconciler"
        for raw_item in _coalesce_items(items):
            item = replace(raw_item, sync_epoch=sync_epoch)
            if item.deleted:
                await self._intake.delete(
                    actor_id=actor_id,
                    source_item_id=item.source_item_id,
                    source_revision=item.source_revision,
                    source_sequence=sequence,
                    sync_epoch=sync_epoch,
                )
                continue
            rejection = (
                "source_too_large"
                if item.size_bytes > self._max_file_size
                else self._intake.policy_rejection(
                    source_name=item.source_name,
                    media_type=item.media_type,
                    size_bytes=item.size_bytes,
                )
            )
            if rejection is not None:
                await self._intake.record_rejection(
                    item=item,
                    source_sequence=sequence,
                    failure_code=rejection,
                )
                continue
            try:
                content = await self._source.download(
                    item.source_item_id,
                    source_revision=item.source_revision,
                    expected_size=item.size_bytes,
                    max_size=self._max_file_size,
                )
            except SharePointRevisionSupersededError:
                await self._intake.record_rejection(
                    item=item,
                    source_sequence=sequence,
                    failure_code="source_revision_superseded",
                )
                continue
            if item.source_name is None:
                raise RuntimeError("SharePoint source name disappeared after policy validation")
            await self._intake.ingest(
                actor_id=actor_id,
                source_item_id=item.source_item_id,
                source_revision=item.source_revision,
                source_name=item.source_name,
                media_type=item.media_type,
                content=content,
                source_sequence=sequence,
                sync_epoch=sync_epoch,
            )

    async def finalize_resync(self, *, connector_id: str, sync_epoch: int, limit: int) -> bool:
        if connector_id != self._config.connector_id:
            raise RuntimeError("SharePoint resync connector binding changed")
        return await self._intake.finalize_resync(
            sync_epoch=sync_epoch,
            limit=limit,
        )


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _stable_uuid(value: str) -> UUID:
    return UUID(bytes=hashlib.sha256(value.encode()).digest()[:16])


def _batch_sequence(idempotency_key: str, connector_id: str) -> int:
    prefix = f"sharepoint-delta:{connector_id}:"
    if not idempotency_key.startswith(prefix):
        raise RuntimeError("SharePoint connector batch identity changed")
    parts = idempotency_key.removeprefix(prefix).split(":")
    if len(parts) == 2:
        epoch_text = "0"
        sequence_text, digest = parts
    elif len(parts) == 3:
        epoch_text, sequence_text, digest = parts
    else:
        raise RuntimeError("SharePoint connector batch identity is invalid")
    if (
        not epoch_text.isdecimal()
        or not sequence_text.isdecimal()
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise RuntimeError("SharePoint connector batch identity is invalid")
    epoch = int(epoch_text)
    sequence = int(sequence_text)
    if sequence >= 1_000_000_000_000:
        raise RuntimeError("SharePoint connector batch sequence exceeds its epoch")
    return epoch * 1_000_000_000_000 + sequence


def _coalesce_items(
    items: Sequence[SharePointDeltaItem],
) -> tuple[SharePointDeltaItem, ...]:
    latest: dict[str, SharePointDeltaItem] = {}
    for item in items:
        latest.pop(item.source_item_id, None)
        latest[item.source_item_id] = item
    return tuple(latest.values())


def _bounded(value: str, field: str) -> None:
    if not value or len(value) > 512:
        raise ValueError(f"{field} MUST be non-empty and bounded")


def _sequence(value: int) -> None:
    if not 0 <= value <= 2**63 - 1:
        raise ValueError("source_sequence MUST be a non-negative signed 64-bit integer")


def _validate_retry(session: UploadSession, *, digest: str, size: int, version_id: UUID) -> None:
    if (
        session.version_id != version_id
        or session.expected_sha256 != digest
        or session.expected_size != size
    ):
        raise RuntimeError("connector upload retry binding changed")
