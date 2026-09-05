"""Cross-tenant Power Platform intake for governed SharePoint documents."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import (
    DocumentNotFoundError,
    DocumentPurpose,
    DocumentState,
    SourceStorageMode,
    UploadSession,
)

from fdai_ingestion_api_service.adapters.sharepoint import SharePointDeltaItem
from fdai_ingestion_api_service.adapters.sharepoint_state import (
    ConnectorBindingConflictError,
    ConnectorDocumentBinding,
)
from fdai_ingestion_api_service.auth import AuthenticationError, ClaimsVerifier
from fdai_ingestion_api_service.ingestion import CreateUploadRequest, DocumentIngestionService

_INGEST_PERMISSION = "DocumentConnector.Ingest"


class PowerPlatformConnectorState(Protocol):
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

    async def complete_cancellation(
        self, *, connector_id: str, source_item_id: str, source_revision: str
    ) -> None: ...

    async def queue_cancellation(
        self, *, connector_id: str, source_item_id: str, source_revision: str
    ) -> None: ...


class ConnectorDeletionService(Protocol):
    async def delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class PowerPlatformConnectorConfig:
    connector_id: str
    source_tenant_id: str
    collection_id: str
    access_descriptor_ref: str
    reader_groups: tuple[str, ...]
    retention_policy_version: str
    purposes: tuple[DocumentPurpose, ...] = (DocumentPurpose.KNOWLEDGE_BASE,)

    def __post_init__(self) -> None:
        values = (
            self.connector_id,
            self.source_tenant_id,
            self.collection_id,
            self.access_descriptor_ref,
            self.retention_policy_version,
        )
        if any(not value or len(value) > 512 for value in values):
            raise ValueError("Power Platform connector policy values MUST be non-empty and bounded")
        try:
            UUID(self.source_tenant_id)
        except ValueError as exc:
            raise ValueError("Power Platform source tenant MUST be a UUID") from exc
        if not self.purposes:
            raise ValueError("Power Platform connector purposes MUST NOT be empty")

    @property
    def binding_id(self) -> str:
        tenant_digest = hashlib.sha256(self.source_tenant_id.encode()).hexdigest()[:16]
        return f"{self.connector_id}:{tenant_digest}"


class PowerPlatformConnectorAuthenticator:
    """Bind an external-tenant token to one server-owned connector policy."""

    def __init__(
        self,
        *,
        verifier: ClaimsVerifier,
        config: PowerPlatformConnectorConfig,
    ) -> None:
        self._verifier = verifier
        self._config = config

    def authenticate(self, authorization_header: str | None) -> str:
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise AuthenticationError("connector authorization requires a bearer token")
        token = authorization_header.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("connector bearer token is empty")
        claims = self._verifier(token)
        if claims.get("tid") != self._config.source_tenant_id:
            raise AuthenticationError("connector source tenant does not match its policy")
        roles = _strings(claims.get("roles"))
        scopes = set(str(claims.get("scp", "")).split())
        if _INGEST_PERMISSION not in roles | scopes:
            raise AuthenticationError("connector token lacks the ingestion permission")
        subject = claims.get("oid") or claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("connector token has no stable subject")
        return f"power-platform:{self._config.connector_id}:{subject}"


class PowerPlatformSharePointConnector:
    """Import push-delivered SharePoint bytes with deterministic retry identities."""

    def __init__(
        self,
        *,
        config: PowerPlatformConnectorConfig,
        service: DocumentIngestionService,
        state: PowerPlatformConnectorState,
        deletion: ConnectorDeletionService | None = None,
    ) -> None:
        self._config = config
        self._service = service
        self._state = state
        self._deletion = deletion

    @property
    def connector_id(self) -> str:
        return self._config.connector_id

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
            f"power-platform:{self._config.binding_id}:{source_item_id}:{source_revision}"
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

    async def delete(
        self,
        *,
        actor_id: str,
        source_item_id: str,
        source_revision: str,
        source_sequence: int,
    ) -> None:
        _bounded(source_item_id, "source_item_id")
        _bounded(source_revision, "source_revision")
        _sequence(source_sequence)
        await self._state.apply_batch(
            connector_id=self._config.binding_id,
            collection_id=self._config.collection_id,
            access_descriptor_ref=self._config.access_descriptor_ref,
            idempotency_key=(
                f"power-platform:{self._config.binding_id}:"
                f"{source_item_id}:{source_revision}:deleted"
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


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _stable_uuid(value: str) -> UUID:
    return UUID(bytes=hashlib.sha256(value.encode()).digest()[:16])


def _bounded(value: str, field: str) -> None:
    if not value or len(value) > 512:
        raise ValueError(f"{field} MUST be non-empty and bounded")


def _sequence(value: int) -> None:
    if not 0 <= value <= 2**63 - 1:
        raise ValueError("source_sequence MUST be a non-negative signed 64-bit integer")


def _strings(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {item for item in value if isinstance(item, str)}


def _validate_retry(session: UploadSession, *, digest: str, size: int, version_id: UUID) -> None:
    if (
        session.version_id != version_id
        or session.expected_sha256 != digest
        or session.expected_size != size
    ):
        raise RuntimeError("connector upload retry binding changed")
