"""Immutable approved-source registry contracts for runtime skills."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

_SOURCE_ID = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_MAX_TEXT = 256


class SkillSourceKind(StrEnum):
    GITHUB_REPOSITORY = "github_repository"


class SkillSourceTrustTier(StrEnum):
    ORGANIZATION_APPROVED = "organization_approved"


class SkillSourceRefreshPolicy(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


@dataclass(frozen=True, slots=True)
class SkillSource:
    source_id: str
    kind: SkillSourceKind
    location: str
    trust_tier: SkillSourceTrustTier
    owner: str
    allowed_path: str
    authentication_audience_ref: str
    refresh_policy: SkillSourceRefreshPolicy
    refresh_interval_seconds: int
    enabled: bool = False

    def __post_init__(self) -> None:
        if _SOURCE_ID.fullmatch(self.source_id) is None:
            raise ValueError("skill source_id MUST be lowercase ASCII")
        if self.kind is not SkillSourceKind.GITHUB_REPOSITORY:
            raise ValueError("only registered GitHub repository sources are supported")
        if _GITHUB_REPOSITORY.fullmatch(self.location) is None:
            raise ValueError("skill source location MUST be an owner/repository identifier")
        for name, value in (
            ("owner", self.owner),
            ("authentication_audience_ref", self.authentication_audience_ref),
        ):
            if not value.strip() or len(value) > _MAX_TEXT or any(ord(char) < 32 for char in value):
                raise ValueError(f"skill source {name} MUST be bounded text")
        _safe_relative_path(self.allowed_path)
        if not 300 <= self.refresh_interval_seconds <= 604_800:
            raise ValueError("skill source refresh_interval_seconds MUST be in [300, 604800]")


class SkillSourceRegistryError(ValueError):
    """A source registration or lifecycle change conflicts with immutable identity."""


class SkillSourceStore(Protocol):
    async def put(self, source: SkillSource, *, now: datetime) -> SkillSource: ...

    async def get(self, source_id: str) -> SkillSource | None: ...

    async def list(self, *, enabled_only: bool = False) -> tuple[SkillSource, ...]: ...

    async def set_enabled(
        self, source_id: str, *, enabled: bool, now: datetime
    ) -> SkillSource | None: ...


class SkillSourceRegistry:
    """Immutable registry; registration and refresh eligibility never imply trust."""

    def __init__(self, sources: Mapping[str, SkillSource] | None = None) -> None:
        self._sources = MappingProxyType(dict(sources or {}))

    def register(self, source: SkillSource) -> SkillSourceRegistry:
        if source.source_id in self._sources:
            raise SkillSourceRegistryError(f"skill source {source.source_id!r} already exists")
        sources = dict(self._sources)
        sources[source.source_id] = source
        return SkillSourceRegistry(sources)

    def enable(self, source_id: str) -> SkillSourceRegistry:
        source = self.get(source_id)
        sources = dict(self._sources)
        sources[source_id] = replace(source, enabled=True)
        return SkillSourceRegistry(sources)

    def disable(self, source_id: str) -> SkillSourceRegistry:
        source = self.get(source_id)
        sources = dict(self._sources)
        sources[source_id] = replace(source, enabled=False)
        return SkillSourceRegistry(sources)

    def get(self, source_id: str) -> SkillSource:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise SkillSourceRegistryError(f"skill source {source_id!r} is not registered") from exc

    def list(self) -> tuple[SkillSource, ...]:
        return tuple(self._sources[source_id] for source_id in sorted(self._sources))


def _safe_relative_path(value: str) -> None:
    if (
        not value
        or len(value) > 512
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("skill source allowed_path MUST be a safe relative path")


__all__ = [
    "SkillSource",
    "SkillSourceKind",
    "SkillSourceRefreshPolicy",
    "SkillSourceRegistry",
    "SkillSourceRegistryError",
    "SkillSourceStore",
    "SkillSourceTrustTier",
]
