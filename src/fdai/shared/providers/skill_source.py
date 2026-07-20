"""Provider-neutral approved skill source fetch contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SkillSourceRateLimitError(RuntimeError):
    def __init__(self, *, retry_at: datetime | None = None) -> None:
        if retry_at is not None and retry_at.tzinfo is None:
            raise ValueError("skill source retry_at MUST include timezone")
        super().__init__("skill source request was rate limited")
        self.retry_at = retry_at


@dataclass(frozen=True, slots=True)
class SkillSourceRevision:
    revision: str | None
    etag: str | None
    not_modified: bool = False

    def __post_init__(self) -> None:
        if self.not_modified:
            if self.revision is not None:
                raise ValueError("not-modified source revision cannot contain a new revision")
        elif self.revision is None or not self.revision.strip():
            raise ValueError("modified source revision MUST be non-empty")


@dataclass(frozen=True, slots=True)
class SkillSourceFile:
    path: str
    content: bytes
    media_type: str
    is_symlink: bool = False


class SkillSourceAdapter(Protocol):
    async def resolve_revision(
        self,
        *,
        repository: str,
        prior_etag: str | None = None,
    ) -> SkillSourceRevision: ...

    async def fetch_files(
        self,
        *,
        repository: str,
        revision: str,
        paths: tuple[str, ...],
    ) -> tuple[SkillSourceFile, ...]: ...


__all__ = [
    "SkillSourceAdapter",
    "SkillSourceFile",
    "SkillSourceRateLimitError",
    "SkillSourceRevision",
]
