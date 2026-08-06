"""Provider-neutral semantic retrieval contracts for catalog artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from fdai.shared.providers.knowledge import Embedder

CatalogSearchMatch = Literal["exact_id", "hybrid"]
CatalogCorpus = Literal["active", "discovery"]
CatalogGenerationState = Literal["staged", "active", "retired", "failed"]
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class CatalogGenerationStaleError(RuntimeError):
    """The requested catalog revision has no matching active generation."""


@dataclass(frozen=True, slots=True)
class CatalogGenerationMetadata:
    """Provider-neutral identity for one complete semantic-index generation."""

    generation_id: str
    generation_digest: str
    corpus: CatalogCorpus
    catalog_digest: str
    semantic_schema_digest: str
    ontology_release_digest: str
    embedding_space_id: str
    embedding_model_version: str
    embedding_dimension: int
    state: CatalogGenerationState = "staged"
    validation_receipt_digest: str | None = None
    activated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.generation_id or len(self.generation_id) > 512:
            raise ValueError("catalog generation id MUST be bounded and non-empty")
        for name, value in (
            ("generation_digest", self.generation_digest),
            ("catalog_digest", self.catalog_digest),
            ("semantic_schema_digest", self.semantic_schema_digest),
            ("ontology_release_digest", self.ontology_release_digest),
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError(f"{name} MUST be a sha256 digest")
        if not self.embedding_space_id or not self.embedding_model_version:
            raise ValueError("catalog generation embedding identity MUST be non-empty")
        if not 1 <= self.embedding_dimension <= 4096:
            raise ValueError("catalog generation embedding dimension MUST be in [1, 4096]")
        if self.validation_receipt_digest is not None:
            if _DIGEST.fullmatch(self.validation_receipt_digest) is None:
                raise ValueError("validation_receipt_digest MUST be a sha256 digest")
        if self.activated_at is not None and self.activated_at.tzinfo is None:
            raise ValueError("catalog generation activated_at MUST be timezone-aware")
        if self.state == "active" and (
            self.validation_receipt_digest is None or self.activated_at is None
        ):
            raise ValueError("active catalog generation MUST carry validation and activation")


@dataclass(frozen=True, slots=True)
class CatalogSearchDocument:
    rule_id: str
    text: str
    neighbor_ids: tuple[str, ...]
    embedding: tuple[float, ...] = ()
    corpus: CatalogCorpus = "active"
    generation_id: str | None = None
    manifest_digest: str | None = None
    surface_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id or not self.text:
            raise ValueError("catalog search document identity and text MUST be non-empty")
        if len(self.neighbor_ids) != len(set(self.neighbor_ids)):
            raise ValueError("catalog search neighbor ids MUST be unique")
        for name, value in (
            ("manifest_digest", self.manifest_digest),
            ("surface_digest", self.surface_digest),
        ):
            if value is not None and _DIGEST.fullmatch(value) is None:
                raise ValueError(f"catalog search {name} MUST be a sha256 digest")


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    rule_id: str
    score: float
    match: CatalogSearchMatch
    components: Mapping[str, float] = field(default_factory=dict)
    corpus: CatalogCorpus = "active"
    generation_id: str | None = None
    generation_digest: str | None = None
    catalog_digest: str | None = None


@runtime_checkable
class CatalogSemanticIndex(Protocol):
    async def upsert(self, documents: Sequence[CatalogSearchDocument]) -> int: ...

    async def synchronize(self, documents: Sequence[CatalogSearchDocument]) -> int:
        """Replace the indexed corpus and return changed plus removed rows."""
        ...

    async def stage_generation(
        self,
        metadata: CatalogGenerationMetadata,
        documents: Sequence[CatalogSearchDocument],
    ) -> int: ...

    async def activate_generation(
        self,
        generation_id: str,
        *,
        expected_generation_digest: str,
        activated_at: datetime,
    ) -> CatalogGenerationMetadata: ...

    async def active_generation(
        self, corpus: CatalogCorpus = "active"
    ) -> CatalogGenerationMetadata | None: ...

    async def search(
        self,
        query: str,
        *,
        k: int = 20,
        corpus: CatalogCorpus = "active",
        expected_catalog_digest: str | None = None,
    ) -> Sequence[CatalogSearchResult]: ...


__all__ = [
    "CatalogSearchDocument",
    "CatalogSearchMatch",
    "CatalogSearchResult",
    "CatalogCorpus",
    "CatalogGenerationMetadata",
    "CatalogGenerationStaleError",
    "CatalogSemanticIndex",
    "Embedder",
]
