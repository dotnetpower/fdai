"""Restart-safe records for trust-verified extensions and skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

_ID = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class TrustedArtifactKind(StrEnum):
    EXTENSION = "extension"
    SKILL = "skill"
    SKILL_BUNDLE = "skill_bundle"


class TrustedArtifactState(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"


@dataclass(frozen=True, slots=True)
class TrustedArtifactRecord:
    """One verified raw artifact and its detached publisher signature."""

    kind: TrustedArtifactKind
    artifact_id: str
    version: str
    source: str
    content_sha256: str
    artifact: bytes
    signature: bytes
    state: TrustedArtifactState
    revision: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if _ID.fullmatch(self.artifact_id) is None:
            raise ValueError("trusted artifact id MUST be lowercase ASCII")
        if _VERSION.fullmatch(self.version) is None:
            raise ValueError("trusted artifact version MUST use MAJOR.MINOR.PATCH")
        if not self.source.strip() or len(self.source) > 512:
            raise ValueError("trusted artifact source MUST be bounded and non-empty")
        if _DIGEST.fullmatch(self.content_sha256) is None:
            raise ValueError("trusted artifact digest MUST be lowercase SHA-256")
        if not self.artifact or len(self.artifact) > _MAX_ARTIFACT_BYTES:
            raise ValueError("trusted artifact bytes MUST be non-empty and bounded")
        if len(self.signature) != 64:
            raise ValueError("trusted artifact signature MUST be 64-byte Ed25519")
        if self.revision < 1:
            raise ValueError("trusted artifact revision MUST be positive")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("trusted artifact timestamps MUST include timezone")
        if self.updated_at < self.created_at:
            raise ValueError("trusted artifact updated_at MUST NOT precede created_at")


class TrustedArtifactConflictError(RuntimeError):
    """A trusted artifact revision changed before a requested write."""


class TrustedArtifactStore(Protocol):
    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord: ...

    async def get(
        self,
        kind: TrustedArtifactKind,
        artifact_id: str,
    ) -> TrustedArtifactRecord | None: ...

    async def list(self, kind: TrustedArtifactKind) -> tuple[TrustedArtifactRecord, ...]: ...


__all__ = [
    "TrustedArtifactConflictError",
    "TrustedArtifactKind",
    "TrustedArtifactRecord",
    "TrustedArtifactState",
    "TrustedArtifactStore",
]
