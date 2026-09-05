"""Write and read verified operational-history artifacts under principal scope."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from fdai.core.ontology_platform.archive_manifest import ArchiveManifest

_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


class OperationalHistoryArtifactStore(Protocol):
    """Content-addressed immutable artifact storage."""

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool: ...

    async def get(self, storage_ref: str) -> bytes | None: ...


class OperationalArchiveArtifactMetadataStore(Protocol):
    """Persist and resolve principal-safe archive artifact metadata."""

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool: ...

    async def get_archive_artifact(
        self,
        manifest_digest: str,
    ) -> OperationalArchiveArtifact | None: ...

    async def is_archive_verified(self, manifest_digest: str) -> bool: ...


class OperationalArchiveManifestStore(Protocol):
    """Persist the manifest before artifact metadata can reference it."""

    async def put_manifest(self, manifest: ArchiveManifest) -> bool: ...


@dataclass(frozen=True, slots=True)
class OperationalArchivePrincipal:
    """Authenticated purpose and scope ceiling for one archive read."""

    principal_id: str
    purpose: str
    scope_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.principal_id or len(self.principal_id) > 512:
            raise ValueError("archive principal_id MUST be bounded non-empty text")
        if not self.purpose or len(self.purpose) > 128:
            raise ValueError("archive purpose MUST be bounded non-empty text")
        if not self.scope_refs or self.scope_refs != tuple(sorted(set(self.scope_refs))):
            raise ValueError("archive principal scope_refs MUST be sorted and unique")


@dataclass(frozen=True, slots=True)
class OperationalArchiveArtifact:
    """Immutable artifact metadata bound to one manifest and access ceiling."""

    artifact_digest: str
    storage_ref: str
    manifest_digest: str
    scope_refs: tuple[str, ...]
    allowed_purposes: tuple[str, ...]
    byte_count: int
    created_at: datetime
    digest: str

    def __post_init__(self) -> None:
        for value in (self.artifact_digest, self.manifest_digest, self.digest):
            _digest(value)
        if self.digest != _sha256(_artifact_body(self)):
            raise ValueError("operational archive artifact digest does not match content")
        if (
            not self.storage_ref.startswith("operational-history/")
            or "%" in self.storage_ref
            or "\\" in self.storage_ref
            or ".." in self.storage_ref.split("/")
        ):
            raise ValueError("operational archive storage_ref is unsafe")
        if self.scope_refs != tuple(sorted(set(self.scope_refs))) or not self.scope_refs:
            raise ValueError("operational archive scope_refs MUST be non-empty and unique")
        if (
            self.allowed_purposes != tuple(sorted(set(self.allowed_purposes)))
            or not self.allowed_purposes
        ):
            raise ValueError("operational archive allowed_purposes MUST be non-empty and unique")
        if not 0 < self.byte_count <= _MAX_ARTIFACT_BYTES:
            raise ValueError("operational archive artifact byte_count is outside its bound")
        if self.created_at.tzinfo is None:
            raise ValueError("operational archive created_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class OperationalArchiveRead:
    """Bounded verified artifact read with no execution authority."""

    manifest_digest: str
    artifact_digest: str
    content: bytes
    observation_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    execution_authority: Literal[False] = False


class OperationalHistoryArchiveWriter:
    """Write canonical observation records to immutable artifact storage."""

    def __init__(
        self,
        *,
        artifacts: OperationalHistoryArtifactStore,
        metadata: OperationalArchiveArtifactMetadataStore,
        manifests: OperationalArchiveManifestStore,
    ) -> None:
        self._artifacts = artifacts
        self._metadata = metadata
        self._manifests = manifests

    async def write(
        self,
        manifest: ArchiveManifest,
        records: Sequence[Mapping[str, object]],
        *,
        scope_refs: tuple[str, ...],
        allowed_purposes: tuple[str, ...],
    ) -> OperationalArchiveArtifact:
        """Write one exact canonical artifact and persist its access metadata."""

        if not manifest.coverage_complete:
            raise ValueError("incomplete archive manifest cannot write a production artifact")
        payload = {
            "schema_version": "1.0.0",
            "source_partition_digests": [
                item.content_digest for item in manifest.source_partitions
            ],
            "records": list(records),
        }
        encoded = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
            + b"\n"
        )
        if len(encoded) > _MAX_ARTIFACT_BYTES:
            raise ValueError("operational archive artifact exceeds its byte bound")
        content_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if content_digest != manifest.archive_content_digest:
            raise ValueError("archive artifact content does not match its manifest")
        storage_ref = f"operational-history/{manifest.digest[7:]}.json"
        normalized_scopes = tuple(sorted(set(scope_refs)))
        normalized_purposes = tuple(sorted(set(allowed_purposes)))
        body = {
            "artifact_digest": content_digest,
            "storage_ref": storage_ref,
            "manifest_digest": manifest.digest,
            "scope_refs": list(normalized_scopes),
            "allowed_purposes": list(normalized_purposes),
            "byte_count": len(encoded),
            "created_at": manifest.created_at.astimezone(UTC).isoformat(),
        }
        artifact = OperationalArchiveArtifact(
            artifact_digest=content_digest,
            storage_ref=storage_ref,
            manifest_digest=manifest.digest,
            scope_refs=normalized_scopes,
            allowed_purposes=normalized_purposes,
            byte_count=len(encoded),
            created_at=manifest.created_at,
            digest=_sha256(body),
        )
        await self._manifests.put_manifest(manifest)
        await self._artifacts.put(storage_ref, encoded, digest=content_digest[7:])
        await self._metadata.put_archive_artifact(artifact)
        return artifact


class OperationalHistoryArchiveReader:
    """Read one verified artifact only within authenticated purpose and scope."""

    def __init__(
        self,
        *,
        artifacts: OperationalHistoryArtifactStore,
        metadata: OperationalArchiveArtifactMetadataStore,
    ) -> None:
        self._artifacts = artifacts
        self._metadata = metadata

    async def read(
        self,
        *,
        principal: OperationalArchivePrincipal,
        manifest_digest: str,
    ) -> OperationalArchiveRead:
        """Return an exact artifact or fail closed on access or integrity mismatch."""

        _digest(manifest_digest)
        artifact = await self._metadata.get_archive_artifact(manifest_digest)
        if artifact is None:
            raise LookupError("operational archive artifact is unavailable")
        if not await self._metadata.is_archive_verified(manifest_digest):
            raise PermissionError("operational archive artifact is not verified")
        if principal.purpose not in artifact.allowed_purposes:
            raise PermissionError("operational archive purpose is not allowed")
        if not set(artifact.scope_refs).issubset(principal.scope_refs):
            raise PermissionError("operational archive scope is not allowed")
        content = await self._artifacts.get(artifact.storage_ref)
        if content is None:
            raise LookupError("operational archive content is unavailable")
        if len(content) != artifact.byte_count:
            raise ValueError("operational archive artifact byte count changed")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != artifact.artifact_digest:
            raise ValueError("operational archive artifact content changed")
        return OperationalArchiveRead(
            manifest_digest=manifest_digest,
            artifact_digest=digest,
            content=content,
        )


def _artifact_body(value: OperationalArchiveArtifact) -> dict[str, object]:
    return {
        "artifact_digest": value.artifact_digest,
        "storage_ref": value.storage_ref,
        "manifest_digest": value.manifest_digest,
        "scope_refs": list(value.scope_refs),
        "allowed_purposes": list(value.allowed_purposes),
        "byte_count": value.byte_count,
        "created_at": value.created_at.astimezone(UTC).isoformat(),
    }


def _digest(value: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("operational archive digest MUST be canonical SHA-256")


def _sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "OperationalArchiveArtifact",
    "OperationalArchiveArtifactMetadataStore",
    "OperationalArchiveManifestStore",
    "OperationalArchivePrincipal",
    "OperationalArchiveRead",
    "OperationalHistoryArchiveReader",
    "OperationalHistoryArchiveWriter",
    "OperationalHistoryArtifactStore",
]
