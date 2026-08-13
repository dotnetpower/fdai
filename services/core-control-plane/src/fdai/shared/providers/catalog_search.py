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
_MAX_DOCUMENT_DIGESTS_PER_CHUNK = 256
_MAX_DOCUMENTS = 20_000
_MAX_DOCUMENT_DIGEST_CHUNKS = (
    _MAX_DOCUMENTS + _MAX_DOCUMENT_DIGESTS_PER_CHUNK - 1
) // _MAX_DOCUMENT_DIGESTS_PER_CHUNK


class CatalogGenerationStaleError(RuntimeError):
    """The requested catalog revision has no matching active generation."""


@dataclass(frozen=True, slots=True)
class CatalogDocumentDigestChunk:
    """Bounded identity for one ordered slice of generation documents."""

    index: int
    document_count: int
    document_digest_root: str

    def __post_init__(self) -> None:
        if self.index < 0 or self.index >= _MAX_DOCUMENT_DIGEST_CHUNKS:
            raise ValueError(
                f"document digest chunk index MUST be in [0, {_MAX_DOCUMENT_DIGEST_CHUNKS - 1}]"
            )
        if not 1 <= self.document_count <= _MAX_DOCUMENT_DIGESTS_PER_CHUNK:
            raise ValueError(
                f"document digest chunk count MUST be in [1, {_MAX_DOCUMENT_DIGESTS_PER_CHUNK}]"
            )
        _require_digest("document_digest_root", self.document_digest_root)

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "index": self.index,
                "document_count": self.document_count,
                "document_digest_root": self.document_digest_root,
            }
        )


@dataclass(frozen=True, slots=True)
class CatalogDocumentDigestManifest:
    """Replayable corpus identity with bounded ordered chunk records."""

    document_count: int
    document_digest_root: str
    chunks: tuple[CatalogDocumentDigestChunk, ...]
    inline_document_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.document_count <= _MAX_DOCUMENTS:
            raise ValueError(f"manifest document count MUST be in [1, {_MAX_DOCUMENTS}]")
        _require_digest("document_digest_root", self.document_digest_root)
        if not self.chunks or len(self.chunks) > _MAX_DOCUMENT_DIGEST_CHUNKS:
            raise ValueError(f"manifest MUST contain 1..{_MAX_DOCUMENT_DIGEST_CHUNKS} chunks")
        indexes = tuple(chunk.index for chunk in self.chunks)
        if indexes != tuple(range(len(self.chunks))):
            raise ValueError("manifest chunk order MUST be contiguous")
        if len({chunk.document_digest_root for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("manifest chunk identities MUST be unique")
        if sum(chunk.document_count for chunk in self.chunks) != self.document_count:
            raise ValueError("manifest chunk document count MUST equal document_count")
        if self.document_digest_root != _chunk_manifest_root(self.chunks):
            raise ValueError("manifest document digest root mismatch")
        if self.document_count <= _MAX_DOCUMENT_DIGESTS_PER_CHUNK:
            if len(self.inline_document_digests) != self.document_count:
                raise ValueError("small manifest MUST carry every inline document digest")
            self.verify_document_digests(self.inline_document_digests)
        elif self.inline_document_digests:
            raise ValueError("corpus-scale manifest MUST NOT carry inline document digests")

    def verify_document_digests(self, values: tuple[str, ...]) -> None:
        """Recompute every chunk from ordered row digests or fail closed."""

        _validate_document_digest_sequence(values)
        if len(values) != self.document_count:
            raise ValueError("manifest document count does not match supplied digests")
        offset = 0
        for chunk in self.chunks:
            upper = offset + chunk.document_count
            if _document_chunk_root(values[offset:upper]) != chunk.document_digest_root:
                raise ValueError("manifest document digest chunk mismatch")
            offset = upper
        if self.inline_document_digests and values != self.inline_document_digests:
            raise ValueError("manifest inline document digests mismatch")


def build_document_digest_manifest(
    document_digests: tuple[str, ...],
) -> CatalogDocumentDigestManifest:
    """Build a bounded hierarchical identity from ordered document digests."""

    _validate_document_digest_sequence(document_digests)
    chunks = tuple(
        CatalogDocumentDigestChunk(
            index=index // _MAX_DOCUMENT_DIGESTS_PER_CHUNK,
            document_count=len(document_digests[index : index + _MAX_DOCUMENT_DIGESTS_PER_CHUNK]),
            document_digest_root=_document_chunk_root(
                document_digests[index : index + _MAX_DOCUMENT_DIGESTS_PER_CHUNK]
            ),
        )
        for index in range(0, len(document_digests), _MAX_DOCUMENT_DIGESTS_PER_CHUNK)
    )
    return CatalogDocumentDigestManifest(
        document_count=len(document_digests),
        document_digest_root=_chunk_manifest_root(chunks),
        chunks=chunks,
        inline_document_digests=(
            document_digests if len(document_digests) <= _MAX_DOCUMENT_DIGESTS_PER_CHUNK else ()
        ),
    )


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
    document_digest_manifest: CatalogDocumentDigestManifest
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
        expected_generation_digest = catalog_generation_digest(
            corpus=self.corpus,
            catalog_digest=self.catalog_digest,
            semantic_schema_digest=self.semantic_schema_digest,
            ontology_release_digest=self.ontology_release_digest,
            embedding_space_id=self.embedding_space_id,
            embedding_model_version=self.embedding_model_version,
            embedding_dimension=self.embedding_dimension,
            document_digest_manifest=self.document_digest_manifest,
        )
        if self.generation_digest != expected_generation_digest:
            raise ValueError("catalog generation digest mismatch")
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
            "reactivated_document_digest_manifest": _manifest_payload(
                reactivated.document_digest_manifest
            ),
            "retired_generation_digest": retired.generation_digest,
            "retired_generation_id": retired.generation_id,
            "retired_document_digest_manifest": _manifest_payload(retired.document_digest_manifest),
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


def catalog_search_document_digest(document: CatalogSearchDocument) -> str:
    """Hash provider-neutral document content without generated embeddings."""

    return _canonical_digest(
        {
            "rule_id": document.rule_id,
            "text": document.text,
            "neighbor_ids": document.neighbor_ids,
            "document_kind": document.document_kind,
            "corpus": document.corpus,
            "manifest_digest": document.manifest_digest,
            "surface_digest": document.surface_digest,
        }
    )


def catalog_generation_digest(
    *,
    corpus: CatalogCorpus,
    catalog_digest: str,
    semantic_schema_digest: str,
    ontology_release_digest: str,
    embedding_space_id: str,
    embedding_model_version: str,
    embedding_dimension: int,
    document_digest_manifest: CatalogDocumentDigestManifest,
) -> str:
    """Return the canonical content identity for one catalog generation."""

    return _canonical_digest(
        {
            "schema_version": "1.0.0",
            "corpus": corpus,
            "catalog_digest": catalog_digest,
            "semantic_schema_digest": semantic_schema_digest,
            "ontology_release_digest": ontology_release_digest,
            "embedding_space_id": embedding_space_id,
            "embedding_model_version": embedding_model_version,
            "embedding_dimension": embedding_dimension,
            "document_digest_manifest": _manifest_payload(document_digest_manifest),
        }
    )


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
        candidate_rule_ids: frozenset[str] | None = None,
    ) -> Sequence[CatalogSearchResult]: ...


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a sha256 digest")


def _validate_document_digest_sequence(values: tuple[str, ...]) -> None:
    if not values or len(values) > _MAX_DOCUMENTS:
        raise ValueError(f"document digests MUST contain 1..{_MAX_DOCUMENTS} values")
    if len(values) != len(set(values)):
        raise ValueError("document digests MUST be unique")
    for value in values:
        _require_digest("document digest", value)


def _document_chunk_root(values: tuple[str, ...]) -> str:
    return _canonical_digest({"document_digests": values})


def _chunk_manifest_root(chunks: tuple[CatalogDocumentDigestChunk, ...]) -> str:
    return _canonical_digest({"chunk_digests": tuple(chunk.digest for chunk in chunks)})


def _manifest_payload(manifest: CatalogDocumentDigestManifest) -> dict[str, object]:
    return {
        "document_count": manifest.document_count,
        "document_digest_root": manifest.document_digest_root,
        "chunk_digests": tuple(chunk.digest for chunk in manifest.chunks),
        "inline_document_digests": manifest.inline_document_digests,
    }


__all__ = [
    "CatalogDocumentDigestChunk",
    "CatalogDocumentDigestManifest",
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
    "build_document_digest_manifest",
    "catalog_generation_digest",
    "catalog_search_document_digest",
]
