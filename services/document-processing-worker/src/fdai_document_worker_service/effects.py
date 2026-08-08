"""Durable service-local records for restart-safe worker external effects."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import (
    DocumentMetadataStore,
    DocumentWorkerClaim,
    UploadSession,
)
from pydantic import BaseModel, ConfigDict, Field


class WorkerEffectKind(StrEnum):
    """External effects that need durable retry or compensation."""

    SOURCE_PROMOTION = "source_promotion"
    EPHEMERAL_SOURCE_CLEANUP = "ephemeral_source_cleanup"


class WorkerEffectStatus(StrEnum):
    """Durable completion state for one idempotent external effect."""

    PENDING = "pending"
    COMPLETED = "completed"


class WorkerEffect(BaseModel):
    """Stable identity and target for one worker-owned external effect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect_id: UUID
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    kind: WorkerEffectKind
    object_key: str = Field(min_length=1, max_length=512)
    status: WorkerEffectStatus
    created_at: datetime
    completed_at: datetime | None = None


class WorkerMetadataStore(DocumentMetadataStore, Protocol):
    """Worker metadata extended with reconciliation cursors and an effect journal."""

    async def list_uploads_by_state_after(
        self,
        state: str,
        *,
        after_upload_id: UUID | None,
        limit: int,
    ) -> tuple[UploadSession, ...]: ...

    async def prepare_worker_effect(
        self,
        *,
        claim: DocumentWorkerClaim,
        kind: WorkerEffectKind,
        document_id: UUID,
        version_id: UUID,
        object_key: str,
    ) -> WorkerEffect: ...

    async def get_worker_effect(
        self, upload_id: UUID, kind: WorkerEffectKind
    ) -> WorkerEffect | None: ...

    async def claim_pending_worker_effects(self, *, limit: int) -> tuple[WorkerEffect, ...]: ...

    async def complete_worker_effect(self, effect_id: UUID) -> None: ...


def worker_effect_id(kind: WorkerEffectKind, version_id: UUID) -> UUID:
    """Return the stable idempotency identity for one version-scoped effect."""
    identity = f"{kind.value}:{version_id}"
    return UUID(bytes=hashlib.sha256(identity.encode()).digest()[:16])
