"""Uploader-scoped governed document references for web chat."""

from __future__ import annotations

from fdai.shared.contracts import DocumentState
from fdai.shared.providers.document_ingestion import (
    ChatDocumentRef,
    DocumentAccessDeniedError,
    DocumentMetadataStore,
    DocumentNotFoundError,
)

_READY_STATES = frozenset({DocumentState.READY, DocumentState.READY_WITH_WARNINGS})


class UploaderDocumentEvidenceResolver:
    """Resolve only ready versions uploaded by the authenticated principal.

    This is the safe baseline for web chat because the read API authorize seam
    currently returns a principal id, not complete collection group claims.
    """

    def __init__(self, *, metadata: DocumentMetadataStore) -> None:
        self._metadata = metadata

    async def resolve(
        self,
        *,
        principal_id: str,
        references: tuple[ChatDocumentRef, ...],
    ) -> tuple[str, ...]:
        evidence: list[str] = []
        for reference in references:
            try:
                version = await self._metadata.get_version(
                    reference.document_id,
                    reference.version_id,
                )
            except DocumentNotFoundError as exc:
                raise DocumentAccessDeniedError(
                    "web chat document evidence access is denied"
                ) from exc
            if (
                version.uploader_id != principal_id
                or version.state not in _READY_STATES
                or not version.available
            ):
                raise DocumentAccessDeniedError("web chat document evidence access is denied")
            evidence.append(f"doc:{version.document_id}:{version.version_id}")
        return tuple(evidence)


__all__ = ["UploaderDocumentEvidenceResolver"]
