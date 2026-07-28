"""Session-scoped content-addressed artifact custody for evaluations."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from fdai_evaluation_sdk import ArtifactPolicy, ArtifactRef, ArtifactSpec


class ArtifactCustodyError(RuntimeError):
    """Artifact publication or access violated a custody policy."""


@dataclass(frozen=True, slots=True)
class ArtifactCustodyRecord:
    """One append-only artifact custody decision."""

    operation: str
    session_id: str
    task_id: str
    artifact_id: str | None
    outcome: str
    occurred_at: datetime


@runtime_checkable
class ArtifactCustodySink(Protocol):
    async def append(self, record: ArtifactCustodyRecord) -> None: ...


class InMemoryArtifactCustodySink:
    """Append-only custody sink for local composition and tests."""

    def __init__(self) -> None:
        self.records: list[ArtifactCustodyRecord] = []
        self._lock = asyncio.Lock()

    async def append(self, record: ArtifactCustodyRecord) -> None:
        async with self._lock:
            self.records.append(record)


@dataclass(frozen=True, slots=True)
class _StoredArtifact:
    reference: ArtifactRef
    content: bytes


class InMemoryArtifactBroker:
    """Bounded in-memory broker that publishes only complete immutable artifacts."""

    def __init__(
        self,
        *,
        custody_sink: ArtifactCustodySink,
        clock: Callable[[], datetime] | None = None,
        chunk_size: int = 64 * 1024,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size MUST be positive")
        self._custody_sink = custody_sink
        self._clock = clock or (lambda: datetime.now(UTC))
        self._chunk_size = chunk_size
        self._records: dict[tuple[str, str, str, str], _StoredArtifact] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self,
        *,
        session_id: str,
        task_id: str,
        spec: ArtifactSpec,
        declared_outputs: tuple[ArtifactSpec, ...],
        chunks: AsyncIterable[bytes],
        policy: ArtifactPolicy,
        ttl_seconds: int,
    ) -> ArtifactRef:
        """Consume a bounded stream and atomically publish its digest-verified reference."""

        try:
            self._validate_publication(spec, declared_outputs, policy, ttl_seconds)
            content = await _read_bounded(chunks, min(spec.max_bytes, policy.max_artifact_bytes))
            digest = hashlib.sha256(content).hexdigest()
            reference = ArtifactRef(
                artifact_id=f"sha256:{digest}",
                session_id=session_id,
                task_id=task_id,
                name=spec.name,
                media_type=spec.media_type,
                size_bytes=len(content),
                sha256=digest,
                expires_at=self._clock() + timedelta(seconds=ttl_seconds),
                executable=spec.executable,
            )
            key = _storage_key(reference)
            async with self._lock:
                session_count = sum(
                    stored.reference.session_id == session_id for stored in self._records.values()
                )
                if session_count >= policy.max_artifacts and key not in self._records:
                    raise ArtifactCustodyError("session artifact count limit exceeded")
                existing = self._records.get(key)
                candidate = _StoredArtifact(reference=reference, content=content)
                if existing is not None and existing != candidate:
                    raise ArtifactCustodyError("artifact identity collision")
                self._records[key] = candidate
        except BaseException:
            await self._audit("publish", session_id, task_id, None, "rejected")
            raise
        await self._audit("publish", session_id, task_id, reference.artifact_id, "accepted")
        return reference

    async def read(
        self,
        *,
        session_id: str,
        artifact: ArtifactRef,
    ) -> AsyncIterator[bytes]:
        """Authorize and verify an artifact before yielding bounded chunks."""

        if artifact.session_id != session_id:
            await self._audit(
                "read", session_id, artifact.task_id, artifact.artifact_id, "cross_session_denied"
            )
            raise ArtifactCustodyError("cross-session artifact access denied")
        async with self._lock:
            stored = self._records.get(_storage_key(artifact))
        if stored is None or stored.reference != artifact:
            await self._audit(
                "read", session_id, artifact.task_id, artifact.artifact_id, "not_found"
            )
            raise ArtifactCustodyError("artifact reference is unknown or altered")
        if artifact.expires_at <= self._clock():
            await self._audit("read", session_id, artifact.task_id, artifact.artifact_id, "expired")
            raise ArtifactCustodyError("artifact reference has expired")
        if hashlib.sha256(stored.content).hexdigest() != artifact.sha256:
            await self._audit(
                "read", session_id, artifact.task_id, artifact.artifact_id, "digest_mismatch"
            )
            raise ArtifactCustodyError("artifact content digest mismatch")
        await self._audit("read", session_id, artifact.task_id, artifact.artifact_id, "accepted")
        for offset in range(0, len(stored.content), self._chunk_size):
            yield stored.content[offset : offset + self._chunk_size]

    async def cleanup_session(self, session_id: str) -> int:
        """Remove all session artifacts and record one teardown audit entry."""

        async with self._lock:
            keys = [
                key
                for key, stored in self._records.items()
                if stored.reference.session_id == session_id
            ]
            task_ids = {self._records[key].reference.task_id for key in keys}
            for key in keys:
                del self._records[key]
        for task_id in sorted(task_ids):
            await self._audit("cleanup", session_id, task_id, None, "completed")
        return len(keys)

    async def _audit(
        self,
        operation: str,
        session_id: str,
        task_id: str,
        artifact_id: str | None,
        outcome: str,
    ) -> None:
        await self._custody_sink.append(
            ArtifactCustodyRecord(
                operation=operation,
                session_id=session_id,
                task_id=task_id,
                artifact_id=artifact_id,
                outcome=outcome,
                occurred_at=self._clock(),
            )
        )

    @staticmethod
    def _validate_publication(
        spec: ArtifactSpec,
        declared_outputs: tuple[ArtifactSpec, ...],
        policy: ArtifactPolicy,
        ttl_seconds: int,
    ) -> None:
        if spec not in declared_outputs:
            raise ArtifactCustodyError("undeclared artifact output rejected")
        if spec.media_type not in policy.allowed_media_types:
            raise ArtifactCustodyError("artifact media type is not allowed")
        if spec.executable and not policy.allow_executable_outputs:
            raise ArtifactCustodyError("executable artifact output is not allowed")
        if spec.ttl_seconds != ttl_seconds:
            raise ArtifactCustodyError("artifact expiry does not match its declaration")
        if not 1 <= ttl_seconds <= policy.max_ttl_seconds:
            raise ArtifactCustodyError("artifact expiry exceeds the session policy")


async def _read_bounded(chunks: AsyncIterable[bytes], limit: int) -> bytes:
    content = bytearray()
    async for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise ArtifactCustodyError("artifact chunks MUST be bytes")
        if len(content) + len(chunk) > limit:
            raise ArtifactCustodyError("artifact content exceeds its byte limit")
        content.extend(chunk)
    return bytes(content)


def _storage_key(reference: ArtifactRef) -> tuple[str, str, str, str]:
    return (
        reference.session_id,
        reference.task_id,
        reference.name,
        reference.artifact_id,
    )


__all__ = [
    "ArtifactCustodyError",
    "ArtifactCustodyRecord",
    "ArtifactCustodySink",
    "InMemoryArtifactBroker",
    "InMemoryArtifactCustodySink",
]
