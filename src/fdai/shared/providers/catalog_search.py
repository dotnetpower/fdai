"""Provider-neutral semantic retrieval contracts for catalog artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from fdai.shared.providers.knowledge import Embedder

CatalogSearchMatch = Literal["exact_id", "hybrid"]


@dataclass(frozen=True, slots=True)
class CatalogSearchDocument:
    rule_id: str
    text: str
    neighbor_ids: tuple[str, ...]
    embedding: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id or not self.text:
            raise ValueError("catalog search document identity and text MUST be non-empty")
        if len(self.neighbor_ids) != len(set(self.neighbor_ids)):
            raise ValueError("catalog search neighbor ids MUST be unique")


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    rule_id: str
    score: float
    match: CatalogSearchMatch


@runtime_checkable
class CatalogSemanticIndex(Protocol):
    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int: ...

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        """Replace the indexed corpus and return changed plus removed rows."""
        ...

    async def search(self, query: str, *, k: int = 20) -> Sequence[CatalogSearchResult]: ...


__all__ = [
    "CatalogSearchDocument",
    "CatalogSearchMatch",
    "CatalogSearchResult",
    "CatalogSemanticIndex",
    "Embedder",
]
