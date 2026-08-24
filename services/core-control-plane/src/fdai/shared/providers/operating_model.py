"""Deployment-supplied operating ontology instance contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .ontology_instance import OntologyLinkRecord, OntologyObjectRecord


@dataclass(frozen=True, slots=True)
class OperatingModelSnapshot:
    """One bounded, versioned service/objective/ownership graph snapshot."""

    source_revision: str
    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]

    def __post_init__(self) -> None:
        if not self.source_revision.strip():
            raise ValueError("OperatingModelSnapshot.source_revision MUST be non-empty")
        if len(self.objects) > 50_000 or len(self.links) > 200_000:
            raise ValueError("operating model snapshot exceeds object/link bounds")
        object_ids = [item.id for item in self.objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("operating model snapshot object ids MUST be unique")
        link_keys = [(item.from_id, item.link_type, item.to_id) for item in self.links]
        if len(link_keys) != len(set(link_keys)):
            raise ValueError("operating model snapshot link identities MUST be unique")


@dataclass(frozen=True, slots=True)
class OperatingModelUpdate:
    """One ordered complete snapshot delivered by a resumable provider."""

    cursor: str
    sequence: int
    snapshot: OperatingModelSnapshot

    def __post_init__(self) -> None:
        if not self.cursor.strip() or len(self.cursor) > 256:
            raise ValueError("OperatingModelUpdate.cursor MUST be 1..256 characters")
        if isinstance(self.sequence, bool) or self.sequence < 0:
            raise ValueError("OperatingModelUpdate.sequence MUST be a non-negative integer")


@runtime_checkable
class OperatingModelProvider(Protocol):
    async def load(self) -> OperatingModelSnapshot:
        """Load one immutable deployment-approved operating model snapshot."""
        ...


@runtime_checkable
class ContinuousOperatingModelProvider(Protocol):
    def updates(
        self,
        *,
        after_cursor: str | None,
        stop: asyncio.Event,
    ) -> AsyncIterator[OperatingModelUpdate]: ...


__all__ = [
    "ContinuousOperatingModelProvider",
    "OperatingModelProvider",
    "OperatingModelSnapshot",
    "OperatingModelUpdate",
]
