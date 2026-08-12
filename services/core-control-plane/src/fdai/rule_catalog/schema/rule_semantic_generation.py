"""Immutable generation and retrieval receipts for Rule semantic search."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,511}$")
_MAX_DIGESTS = 256
_MAX_DOCUMENTS = 20_000
_MAX_CHUNKS = (_MAX_DOCUMENTS + _MAX_DIGESTS - 1) // _MAX_DIGESTS


class GenerationState(StrEnum):
    STAGED = "staged"
    ACTIVE = "active"
    RETIRED = "retired"
    FAILED = "failed"


class RetrievalOperation(StrEnum):
    DISCOVER = "discover"
    EXPLAIN = "explain"
    EVALUATE = "evaluate"
    ACTION_DRAFT = "action_draft"


class SemanticAvailability(StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class CatalogDocumentDigestChunk:
    """Bounded identity for one ordered slice of generation documents."""

    index: int
    document_count: int
    document_digest_root: str

    def __post_init__(self) -> None:
        if self.index < 0 or self.index >= _MAX_CHUNKS:
            raise ValueError(f"document digest chunk index MUST be in [0, {_MAX_CHUNKS - 1}]")
        if not 1 <= self.document_count <= _MAX_DIGESTS:
            raise ValueError(f"document digest chunk count MUST be in [1, {_MAX_DIGESTS}]")
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
        if not self.chunks or len(self.chunks) > _MAX_CHUNKS:
            raise ValueError(f"manifest MUST contain 1..{_MAX_CHUNKS} chunks")
        indexes = tuple(chunk.index for chunk in self.chunks)
        if indexes != tuple(range(len(self.chunks))):
            raise ValueError("manifest chunk order MUST be contiguous")
        if len({chunk.document_digest_root for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("manifest chunk identities MUST be unique")
        if sum(chunk.document_count for chunk in self.chunks) != self.document_count:
            raise ValueError("manifest chunk document count MUST equal document_count")
        if self.document_digest_root != _chunk_manifest_root(self.chunks):
            raise ValueError("manifest document digest root mismatch")
        if self.document_count <= _MAX_DIGESTS:
            if len(self.inline_document_digests) != self.document_count:
                raise ValueError("small manifest MUST carry every inline document digest")
            self.verify_document_digests(self.inline_document_digests)
        elif self.inline_document_digests:
            raise ValueError("corpus-scale manifest MUST NOT carry inline document digests")

    def verify_document_digests(self, values: tuple[str, ...]) -> None:
        """Recompute every chunk from ordered row digests or fail closed."""

        _document_digest_sequence(values)
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

    _document_digest_sequence(document_digests)
    chunks = tuple(
        CatalogDocumentDigestChunk(
            index=index // _MAX_DIGESTS,
            document_count=len(document_digests[index : index + _MAX_DIGESTS]),
            document_digest_root=_document_chunk_root(
                document_digests[index : index + _MAX_DIGESTS]
            ),
        )
        for index in range(0, len(document_digests), _MAX_DIGESTS)
    )
    return CatalogDocumentDigestManifest(
        document_count=len(document_digests),
        document_digest_root=_chunk_manifest_root(chunks),
        chunks=chunks,
        inline_document_digests=(document_digests if len(document_digests) <= _MAX_DIGESTS else ()),
    )


@dataclass(frozen=True, slots=True)
class CatalogSearchGeneration:
    """One complete and atomically activatable semantic-index generation."""

    generation_id: str
    corpus: RuleCorpus
    catalog_digest: str
    semantic_schema_digest: str
    ontology_release_digest: str
    embedding_space_id: str
    embedding_model_version: str
    embedding_dimension: int
    document_digests: tuple[str, ...]
    document_digest_manifest: CatalogDocumentDigestManifest | None = None
    state: GenerationState = GenerationState.STAGED
    validation_receipt_digest: str | None = None
    activated_at: datetime | None = None
    projection_authority: str = "projection_only"
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for name, value in (
            ("generation_id", self.generation_id),
            ("embedding_space_id", self.embedding_space_id),
            ("embedding_model_version", self.embedding_model_version),
            ("schema_version", self.schema_version),
        ):
            _bounded_identifier(name, value)
        for name, value in (
            ("catalog_digest", self.catalog_digest),
            ("semantic_schema_digest", self.semantic_schema_digest),
            ("ontology_release_digest", self.ontology_release_digest),
        ):
            _require_digest(name, value)
        if self.document_digest_manifest is None:
            _ordered_digests("document_digests", self.document_digests)
        elif self.document_digests:
            if self.document_digests != self.document_digest_manifest.inline_document_digests:
                raise ValueError("generation inline document digests MUST match its manifest")
        if not 1 <= self.embedding_dimension <= 4096:
            raise ValueError("embedding_dimension MUST be in [1, 4096]")
        if self.validation_receipt_digest is not None:
            _require_digest("validation_receipt_digest", self.validation_receipt_digest)
        if self.activated_at is not None and self.activated_at.tzinfo is None:
            raise ValueError("generation activated_at MUST be timezone-aware")
        if self.state is GenerationState.ACTIVE and (
            self.validation_receipt_digest is None or self.activated_at is None
        ):
            raise ValueError("active generation MUST carry validation and activation evidence")
        if self.state is GenerationState.STAGED and self.activated_at is not None:
            raise ValueError("staged generation MUST NOT carry activated_at")
        if self.projection_authority != "projection_only":
            raise ValueError("search generation MUST remain projection_only")

    @property
    def digest(self) -> str:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generation_id": self.generation_id,
            "corpus": self.corpus.value,
            "catalog_digest": self.catalog_digest,
            "semantic_schema_digest": self.semantic_schema_digest,
            "ontology_release_digest": self.ontology_release_digest,
            "embedding_space_id": self.embedding_space_id,
            "embedding_model_version": self.embedding_model_version,
            "embedding_dimension": self.embedding_dimension,
            "document_digests": self.document_digests,
            "state": self.state.value,
            "validation_receipt_digest": self.validation_receipt_digest,
            "activated_at": _timestamp(self.activated_at),
            "projection_authority": self.projection_authority,
        }
        if self.document_digest_manifest is not None:
            payload["document_digest_manifest"] = {
                "document_count": self.document_digest_manifest.document_count,
                "document_digest_root": self.document_digest_manifest.document_digest_root,
                "chunks": tuple(chunk.digest for chunk in self.document_digest_manifest.chunks),
                "inline_document_digests": (self.document_digest_manifest.inline_document_digests),
            }
        return _canonical_digest(payload)


@dataclass(frozen=True, slots=True)
class RetrievalRank:
    rule_ref: str
    rank: int
    components: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        _bounded_identifier("rule_ref", self.rule_ref)
        if self.rank < 1:
            raise ValueError("retrieval rank MUST be positive")
        names = tuple(name for name, _ in self.components)
        if names != tuple(sorted(set(names))):
            raise ValueError("retrieval components MUST be unique and ordered")
        for name, value in self.components:
            _bounded_identifier("retrieval component", name)
            if not math.isfinite(value):
                raise ValueError("retrieval component value MUST be finite")


@dataclass(frozen=True, slots=True)
class CatalogRetrievalReceipt:
    """Read-only proof of one bounded search over an exact catalog generation."""

    query_digest: str
    operation: RetrievalOperation
    corpus: RuleCorpus
    catalog_digest: str
    semantic_state: SemanticAvailability
    results: tuple[RetrievalRank, ...]
    generation_digest: str | None = None
    degraded_reason: str | None = None
    unresolved_terms: tuple[str, ...] = ()
    clarification_required: bool = False
    truncated: bool = False
    execution_authority: bool = False
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        _require_digest("query_digest", self.query_digest)
        _require_digest("catalog_digest", self.catalog_digest)
        _bounded_identifier("schema_version", self.schema_version)
        if self.generation_digest is not None:
            _require_digest("generation_digest", self.generation_digest)
        if self.semantic_state is SemanticAvailability.AVAILABLE and self.generation_digest is None:
            raise ValueError("available semantic retrieval MUST name a generation")
        if (
            self.semantic_state
            in {
                SemanticAvailability.UNAVAILABLE,
                SemanticAvailability.DISABLED,
            }
            and self.generation_digest is not None
        ):
            raise ValueError("unavailable semantic retrieval MUST NOT name a generation")
        if self.semantic_state is not SemanticAvailability.AVAILABLE:
            if self.degraded_reason is None:
                raise ValueError("degraded semantic retrieval MUST include a reason")
            _bounded_identifier("degraded_reason", self.degraded_reason)
        if self.unresolved_terms != tuple(sorted(set(self.unresolved_terms))):
            raise ValueError("retrieval unresolved_terms MUST be unique and ordered")
        for value in self.unresolved_terms:
            _bounded_identifier("unresolved_term", value)
        if self.unresolved_terms and not self.clarification_required:
            raise ValueError("unresolved retrieval terms MUST require clarification")
        if self.clarification_required and self.results:
            raise ValueError("clarification receipt MUST NOT claim ranked Rule results")
        if (
            self.operation
            in {
                RetrievalOperation.EVALUATE,
                RetrievalOperation.ACTION_DRAFT,
            }
            and self.corpus is not RuleCorpus.ACTIVE
        ):
            raise ValueError("evaluation and action drafts MUST use the active corpus")
        ranks = tuple(item.rank for item in self.results)
        refs = tuple(item.rule_ref for item in self.results)
        if ranks != tuple(range(1, len(self.results) + 1)):
            raise ValueError("retrieval results MUST use contiguous rank order")
        if len(refs) != len(set(refs)):
            raise ValueError("retrieval result Rule refs MUST be unique")
        if self.execution_authority:
            raise ValueError("catalog retrieval receipt MUST NOT carry execution authority")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "query_digest": self.query_digest,
                "operation": self.operation.value,
                "corpus": self.corpus.value,
                "catalog_digest": self.catalog_digest,
                "semantic_state": self.semantic_state.value,
                "generation_digest": self.generation_digest,
                "results": [(item.rule_ref, item.rank, item.components) for item in self.results],
                "degraded_reason": self.degraded_reason,
                "unresolved_terms": self.unresolved_terms,
                "clarification_required": self.clarification_required,
                "truncated": self.truncated,
                "execution_authority": self.execution_authority,
            }
        )


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _bounded_identifier(name: str, value: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a bounded ASCII identifier")


def _require_digest(name: str, value: str) -> None:
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a sha256 digest")


def _ordered_digests(name: str, values: tuple[str, ...]) -> None:
    if not values or len(values) > _MAX_DIGESTS:
        raise ValueError(f"{name} MUST contain 1..{_MAX_DIGESTS} digests")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be unique and ordered")
    for value in values:
        _require_digest(name, value)


def _document_digest_sequence(values: tuple[str, ...]) -> None:
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


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


__all__ = [
    "CatalogDocumentDigestChunk",
    "CatalogDocumentDigestManifest",
    "CatalogRetrievalReceipt",
    "CatalogSearchGeneration",
    "GenerationState",
    "RetrievalOperation",
    "RetrievalRank",
    "SemanticAvailability",
    "build_document_digest_manifest",
]
