"""Governed immutable-source download with authorization and audit admission."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentLifecycleEvent,
    DocumentObjectStore,
    DocumentState,
    DocumentUploadMetadataStore,
    DocumentVersion,
    ProtectionState,
)

from fdai_ingestion_api_service.download_authorization import (
    SourceDownloadAuthorization,
    SourceDownloadAuthorizer,
)
from fdai_ingestion_api_service.providers import DocumentDownload


class GovernedDocumentDownload:
    """Admit immutable source bytes only after current access, protection, and audit."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentUploadMetadataStore,
        objects: DocumentObjectStore,
        protection: SourceDownloadAuthorizer | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._access = access
        self._metadata = metadata
        self._objects = objects
        self._protection = protection
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory = id_factory or uuid4

    @property
    def supports_protected_source_download(self) -> bool:
        return self._protection is not None

    async def download(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentDownload:
        """Return one retained available source version after authorization and audit."""
        version = await self._metadata.get_version(document_id, version_id)
        await self._access.authorize_read(
            actor_id=actor_id,
            actor_groups=actor_groups,
            version=version,
        )
        if not version.available or version.state not in {
            DocumentState.READY,
            DocumentState.READY_WITH_WARNINGS,
        }:
            raise DocumentAccessDeniedError("document version is not available for download")
        receipt: SourceDownloadAuthorization | None = None
        if version.protection_state not in {
            ProtectionState.NONE,
            ProtectionState.LABELED_UNENCRYPTED,
        }:
            if (
                version.protection_state != ProtectionState.RIGHTS_MANAGED_ACCESSIBLE
                or self._protection is None
            ):
                raise DocumentAccessDeniedError(
                    "protected source download requires purpose-specific authorization"
                )
            receipt = await self._protection.authorize(
                actor_id=actor_id,
                actor_groups=actor_groups,
                version=version,
            )
            self._check_validity(receipt)
            await self._revalidate(
                actor_id=actor_id,
                actor_groups=actor_groups,
                version=version,
            )
        session = await self._metadata.get_upload(version.upload_id)
        if (
            session.document_id != document_id
            or session.version_id != version_id
            or session.upload_id != version.upload_id
            or session.expected_sha256 != version.source_sha256
            or session.expected_size != version.size_bytes
        ):
            raise DocumentAccessDeniedError("document download binding changed")

        event_id = self._id_factory()
        requested_at = self._clock()
        authorization_fields: dict[str, object] = {}
        if receipt is not None:
            self._check_validity(receipt)
            authorization_fields = {
                "authorization_request_id": str(receipt.request_id),
                "authorization_receipt_sha256": receipt.receipt_sha256,
                "authorization_receipt_json": receipt.canonical_receipt,
                "authorization_issued_at": receipt.issued_at.isoformat(),
                "authorization_expires_at": receipt.expires_at.isoformat(),
                "authorization_purpose": "governed_source_download",
                "document_revision": version.revision,
                "source_sha256": version.source_sha256,
                "access_descriptor_ref": version.access.reference,
                "protection_policy_revision": version.protection_policy_revision,
            }
        await self._metadata.enqueue_event(
            DocumentLifecycleEvent(
                event_id=event_id,
                idempotency_key=f"document.source_download_requested:{event_id}",
                topic="object.event",
                key=str(document_id),
                payload={
                    "producer_principal": "Huginn",
                    "kind": "document_ingestion",
                    "action": "document.source_download_requested",
                    "event_type": "document.source_download_requested",
                    "correlation_id": str(version.upload_id),
                    "idempotency_key": f"document.source_download_requested:{event_id}",
                    "resource_id": str(document_id),
                    "resource_type": "document",
                    "document_id": str(document_id),
                    "version_id": str(version_id),
                    "actor_id": actor_id,
                    **authorization_fields,
                },
                created_at=requested_at,
            )
        )

        async def content() -> AsyncIterator[bytes]:
            if receipt is not None:
                self._check_validity(receipt)
                await self._revalidate(
                    actor_id=actor_id, actor_groups=actor_groups, version=version
                )
                self._check_validity(receipt)
            async for chunk in self._objects.read(session.object_key):
                if receipt is not None:
                    await self._revalidate(
                        actor_id=actor_id, actor_groups=actor_groups, version=version
                    )
                    self._check_validity(receipt)
                yield chunk

        return DocumentDownload(version=version, content=content())

    def _check_validity(self, receipt: SourceDownloadAuthorization) -> None:
        if not receipt.issued_at <= self._clock() < receipt.expires_at:
            raise DocumentAccessDeniedError(
                "source download authorization expired or clock changed"
            )

    async def _revalidate(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        current = await self._metadata.get_version(version.document_id, version.version_id)
        if current != version:
            raise DocumentAccessDeniedError("document download authorization binding changed")
        await self._access.authorize_read(
            actor_id=actor_id, actor_groups=actor_groups, version=current
        )
