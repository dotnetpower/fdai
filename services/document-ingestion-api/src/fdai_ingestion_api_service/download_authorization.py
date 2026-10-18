"""Purpose-specific provider admission for immutable source export."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from fdai_service_contracts import DocumentVersion


@dataclass(frozen=True, slots=True)
class SourceDownloadAuthorization:
    """A request-bound provider decision, never a reusable preview permission."""

    request_id: UUID
    canonical_receipt: str
    issued_at: datetime
    expires_at: datetime

    @property
    def receipt_sha256(self) -> str:
        return hashlib.sha256(self.canonical_receipt.encode()).hexdigest()


class SourceDownloadAuthorizer(Protocol):
    async def authorize(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> SourceDownloadAuthorization:
        """Verify exact source, actor, policy, purpose, nonce, and bounded validity."""
        ...
