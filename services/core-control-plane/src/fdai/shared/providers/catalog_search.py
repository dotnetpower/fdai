"""Provider-neutral semantic retrieval contracts for catalog artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from fdai.shared.ontology.compatibility import OntologyGenerationCompatibilityReceipt
from fdai.shared.providers.knowledge import Embedder

CatalogSearchMatch = Literal["exact_id", "hybrid"]
CatalogCorpus = Literal["active", "discovery"]
CatalogGenerationState = Literal["staged", "active", "retired", "failed"]
CatalogDocumentKind = Literal["rule", "ontology_declaration", "ontology_object"]
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
class CatalogGenerationRollbackReceipt:
    """Replay-stable proof of one atomic active-generation rollback."""

    retired_generation: CatalogGenerationMetadata
    reactivated_generation: CatalogGenerationMetadata
    validation_receipt_digest: str
    ontology_compatibility_receipt: OntologyGenerationCompatibilityReceipt
    rolled_back_at: datetime
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        retired = self.retired_generation
        reactivated = self.reactivated_generation
        if retired.state != "retired" or reactivated.state != "active":
            raise ValueError("catalog rollback receipt MUST describe retired and active states")
        if retired.corpus != reactivated.corpus:
            raise ValueError("catalog rollback generations MUST share one corpus")
        compatibility = self.ontology_compatibility_receipt
        if (
            compatibility.previous_release_digest != reactivated.ontology_release_digest
            or compatibility.candidate_release_digest != retired.ontology_release_digest
        ):
            raise ValueError("catalog rollback ontology compatibility receipt mismatch")
        if reactivated.validation_receipt_digest != self.validation_receipt_digest:
            raise ValueError("catalog rollback validation receipt mismatch")
        if _DIGEST.fullmatch(self.validation_receipt_digest) is None:
            raise ValueError("catalog rollback validation receipt MUST be a sha256 digest")
        if self.rolled_back_at.tzinfo is None:
            raise ValueError("catalog rollback time MUST be timezone-aware")
        payload = {
            "corpus": retired.corpus,
            "ontology_compatibility": {
                "added_declarations": compatibility.added_declarations,
                "candidate_release_digest": compatibility.candidate_release_digest,
                "checked_declarations": compatibility.checked_declarations,
                "previous_release_digest": compatibility.previous_release_digest,
            },
            "reactivated_generation_digest": reactivated.generation_digest,
            "reactivated_generation_id": reactivated.generation_id,
            "retired_generation_digest": retired.generation_digest,
            "retired_generation_id": retired.generation_id,
            "rolled_back_at": self.rolled_back_at.isoformat(),
            "validation_receipt_digest": self.validation_receipt_digest,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "receipt_digest", f"sha256:{hashlib.sha256(encoded).hexdigest()}")

    @property
    def retired_generation_id(self) -> str:
        return self.retired_generation.generation_id

    @property
    def reactivated_generation_id(self) -> str:
        return self.reactivated_generation.generation_id


@dataclass(frozen=True, slots=True)
class CatalogSearchDocument:
    """One candidate-only semantic projection row.

    ``rule_id`` remains the compatibility identifier. For non-Rule rows it
    stores a namespaced declaration or deployment-local object reference.
    """

    rule_id: str
    text: str
    neighbor_ids: tuple[str, ...]
    document_kind: CatalogDocumentKind = "rule"
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
        if len(self.embedding) > 4096 or any(not math.isfinite(item) for item in self.embedding):
            raise ValueError("catalog search embedding MUST be finite and bounded")
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
    document_kind: CatalogDocumentKind = "rule"

    def __post_init__(self) -> None:
        if not math.isfinite(self.score):
            raise ValueError("catalog search result score MUST be finite")
        if any(not math.isfinite(value) for value in self.components.values()):
            raise ValueError("catalog search result components MUST be finite")


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

    async def rollback_generation(
        self,
        target_generation_id: str,
        *,
        expected_active_generation_id: str,
        expected_active_generation_digest: str,
        expected_target_generation_digest: str,
        expected_validation_receipt_digest: str,
        ontology_compatibility_receipt: OntologyGenerationCompatibilityReceipt,
        rolled_back_at: datetime,
    ) -> CatalogGenerationRollbackReceipt:
        """Atomically reactivate one validated retained generation."""
        ...

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
    "CatalogDocumentKind",
    "CatalogSearchDocument",
    "CatalogSearchMatch",
    "CatalogSearchResult",
    "CatalogCorpus",
    "CatalogGenerationMetadata",
    "CatalogGenerationRollbackReceipt",
    "CatalogGenerationStaleError",
    "CatalogSemanticIndex",
    "Embedder",
]
