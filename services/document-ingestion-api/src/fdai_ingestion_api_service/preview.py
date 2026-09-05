"""Governed extracted-document preview with source and provider authorization."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from fdai_service_contracts import (
    DocumentAccessDeniedError,
    DocumentAccessProvider,
    DocumentEnvelope,
    DocumentUploadMetadataStore,
    DocumentVersion,
    ProtectionState,
)


class DocumentArtifactReader(Protocol):
    async def read_artifact(self, document_id: UUID, version_id: UUID) -> DocumentEnvelope: ...


class PreviewProtectionAuthorizer(Protocol):
    async def authorize(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None: ...


class MetadataPreviewProtectionAuthorizer:
    """Allow unprotected previews and hold rights-managed content without a provider."""

    async def authorize(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        del actor_id, actor_groups
        if version.protection_state not in {
            ProtectionState.NONE,
            ProtectionState.LABELED_UNENCRYPTED,
        }:
            raise DocumentAccessDeniedError(
                "rights-managed preview requires delegated provider authorization"
            )


class GovernedDocumentPreview:
    """Return bounded extracted units only after both authorization checks."""

    def __init__(
        self,
        *,
        access: DocumentAccessProvider,
        metadata: DocumentUploadMetadataStore,
        artifacts: DocumentArtifactReader,
        protection: PreviewProtectionAuthorizer,
        max_units: int = 200,
        max_characters: int = 100_000,
    ) -> None:
        if max_units < 1 or max_characters < 1:
            raise ValueError("preview bounds MUST be positive")
        self._access = access
        self._metadata = metadata
        self._artifacts = artifacts
        self._protection = protection
        self._max_units = max_units
        self._max_characters = max_characters

    async def preview(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentEnvelope:
        version = await self._metadata.get_version(document_id, version_id)
        await self._access.authorize_read(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        if not version.available or not version.active:
            raise DocumentAccessDeniedError("document version is not available for preview")
        await self._protection.authorize(
            actor_id=actor_id, actor_groups=actor_groups, version=version
        )
        envelope = await self._artifacts.read_artifact(document_id, version_id)
        if (
            envelope.source_sha256 != version.source_sha256
            or envelope.access_descriptor_ref != version.access.reference
        ):
            raise DocumentAccessDeniedError("document preview binding changed")
        characters = sum(len(unit.text) for unit in envelope.units)
        if len(envelope.units) > self._max_units or characters > self._max_characters:
            raise ValueError("document preview exceeds the configured bound")
        return envelope
