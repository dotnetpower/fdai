"""Injected provider contracts for Document Ingestion API composition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import DocumentVersion


class ApplicationFactory(Protocol):
    """Build one ASGI application from a validated environment snapshot."""

    def __call__(self, environ: Mapping[str, str]) -> object: ...


class DocumentDeletionService(Protocol):
    """Delete one governed version without importing worker implementation code."""

    async def delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion: ...


class HandoverArtifact(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class HandoverDraftReader(Protocol):
    async def get(self, upload_id: UUID) -> HandoverArtifact: ...


@dataclass(frozen=True, slots=True)
class StewardshipWebhookResult:
    """HTTP-safe result of one signed stewardship webhook delivery."""

    accepted: bool
    reason: str
    changed: bool = False


class StewardshipWebhook(Protocol):
    async def handle(
        self, *, headers: Mapping[str, str], body: bytes
    ) -> StewardshipWebhookResult: ...
