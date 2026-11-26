"""Content-addressed in-memory storage and append-only custody adapters."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Mapping
from datetime import datetime

from fdai.shared.providers.browser_evidence import (
    BrowserEvidenceArtifact,
    StoredBrowserEvidence,
)
from fdai.shared.providers.state_store import StateStore


class InMemoryBrowserEvidenceArtifactStore:
    def __init__(self) -> None:
        self._records: dict[str, StoredBrowserEvidence] = {}
        self._lock = asyncio.Lock()

    async def put(self, evidence: StoredBrowserEvidence) -> bool:
        verify_stored_browser_evidence(evidence)
        async with self._lock:
            existing = self._records.get(evidence.artifact.artifact_id)
            if existing is not None:
                if existing != evidence:
                    raise ValueError("browser artifact id collision")
                return False
            self._records[evidence.artifact.artifact_id] = evidence
            return True

    async def get(self, artifact_id: str) -> StoredBrowserEvidence | None:
        async with self._lock:
            return self._records.get(artifact_id)

    async def list_artifacts(self, *, limit: int) -> tuple[BrowserEvidenceArtifact, ...]:
        if limit < 1:
            raise ValueError("browser artifact list limit MUST be positive")
        async with self._lock:
            records = sorted(
                (record.artifact for record in self._records.values()),
                key=lambda item: (item.captured_at, item.artifact_id),
                reverse=True,
            )
            return tuple(records[:limit])

    async def purge_expired(self, *, now: datetime, limit: int) -> tuple[str, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("browser artifact retention limit MUST be in [1, 500]")
        async with self._lock:
            expired = sorted(
                (
                    record.artifact
                    for record in self._records.values()
                    if record.artifact.expires_at <= now
                ),
                key=lambda item: (item.expires_at, item.artifact_id),
            )[:limit]
            for artifact in expired:
                del self._records[artifact.artifact_id]
            return tuple(artifact.artifact_id for artifact in expired)


class InMemoryBrowserEvidenceCustodySink:
    def __init__(self) -> None:
        self.records: list[Mapping[str, str]] = []

    async def record_capture(
        self,
        *,
        request_id: str,
        policy_ref: str,
        content_digest: str,
        captured_at: datetime,
        correlation_id: str,
    ) -> str:
        reference = f"browser-custody:{len(self.records) + 1}"
        self.records.append(
            {
                "audit_ref": reference,
                "request_id": request_id,
                "policy_ref": policy_ref,
                "content_digest": content_digest,
                "captured_at": captured_at.isoformat(),
                "correlation_id": correlation_id,
            }
        )
        return reference


class StateStoreBrowserEvidenceCustodySink:
    """Link captures idempotently to the existing append-only audit chain."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    async def record_capture(
        self,
        *,
        request_id: str,
        policy_ref: str,
        content_digest: str,
        captured_at: datetime,
        correlation_id: str,
    ) -> str:
        reference = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"browser-evidence:{request_id}:{content_digest}",
            )
        )
        await self._state_store.write_state_with_audit_if_absent(
            f"browser-evidence:custody:{reference}",
            {
                "audit_ref": reference,
                "request_id": request_id,
                "content_digest": content_digest,
            },
            {
                "event_id": reference,
                "correlation_id": correlation_id,
                "actor": "fdai.browser_evidence",
                "action_kind": "browser_evidence.capture",
                "mode": "shadow",
                "request_id": request_id,
                "policy_ref": policy_ref,
                "content_digest": content_digest,
                "untrusted": True,
                "can_authorize_action": False,
                "captured_at": captured_at.isoformat(),
            },
        )
        return reference


def verify_stored_browser_evidence(evidence: StoredBrowserEvidence) -> None:
    """Fail closed when persisted payload bytes do not match artifact hashes."""
    artifact = evidence.artifact
    payload = evidence.payload
    if artifact.artifact_id != f"sha256:{artifact.content_digest}":
        raise ValueError("browser artifact id does not match content digest")
    if artifact.screenshot_hash != _optional_hash(payload.screenshot):
        raise ValueError("browser screenshot hash mismatch")
    if artifact.text_hash != _optional_hash(payload.visible_text):
        raise ValueError("browser visible text hash mismatch")
    if artifact.snapshot_hash != _optional_hash(payload.aria_snapshot):
        raise ValueError("browser snapshot hash mismatch")


def _optional_hash(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    encoded = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "InMemoryBrowserEvidenceArtifactStore",
    "InMemoryBrowserEvidenceCustodySink",
    "StateStoreBrowserEvidenceCustodySink",
    "verify_stored_browser_evidence",
]
