"""Deployment-supplied operating ontology instance contract."""

from __future__ import annotations

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


@runtime_checkable
class OperatingModelProvider(Protocol):
    async def load(self) -> OperatingModelSnapshot:
        """Load one immutable deployment-approved operating model snapshot."""
        ...


__all__ = ["OperatingModelProvider", "OperatingModelSnapshot"]
