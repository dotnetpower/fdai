"""Bounded retention reconciliation for temporary document versions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts import (
    DocumentLifecycleConflictError,
    DocumentNotFoundError,
    DocumentUploadMetadataStore,
    DocumentVersion,
)

from fdai_ingestion_api_service.deletion import ApiDocumentDeletionService


class RetentionMetadataStore(DocumentUploadMetadataStore, Protocol):
    """Expose deadline-ordered temporary versions without owning deletion."""

    async def list_due_temporary_versions(
        self, *, now: datetime, limit: int
    ) -> tuple[DocumentVersion, ...]: ...


class DocumentRetentionReconciler:
    """Submit a bounded batch of replay-safe expiry deletion requests."""

    def __init__(
        self,
        *,
        metadata: RetentionMetadataStore,
        deletion: ApiDocumentDeletionService,
        batch_limit: int = 100,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if batch_limit < 1 or batch_limit > 1000:
            raise ValueError("retention batch_limit MUST be in [1, 1000]")
        self._metadata = metadata
        self._deletion = deletion
        self._batch_limit = batch_limit
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def run_once(self) -> int:
        """Submit each due version once; concurrent CAS winners remain authoritative."""
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("retention reconciliation time MUST include a timezone")
        due = await self._metadata.list_due_temporary_versions(
            now=now,
            limit=self._batch_limit,
        )
        submitted = 0
        for version in due:
            try:
                await self._deletion.expire(
                    document_id=version.document_id,
                    version_id=version.version_id,
                )
            except (DocumentLifecycleConflictError, DocumentNotFoundError, ValueError):
                continue
            submitted += 1
        return submitted


__all__ = ["DocumentRetentionReconciler", "RetentionMetadataStore"]
