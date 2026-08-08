"""Knowledge base ingestion + retrieval - CSP-neutral RAG seam.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.2`` (telemetry /
grounding inputs) and the grounding rule in
``architecture.instructions.md § LLM Quality Gate`` ("force citation of the
rules/policies that justify the judgment; abstain when unsupported").

FDAI grounds T2 reasoning on the structured rule catalog + ontology today.
This seam adds the missing free-form leg: ingest arbitrary operator
documents (architecture notes, runbooks, wiki exports), chunk + embed them,
and retrieve the top-k chunks - **with citations** - to ground a judgment.
It is the FDAI counterpart of Azure SRE Agent's Knowledge Base.

Layering
--------

This module lives under ``shared/providers`` and MUST NOT import
``core/``. It therefore declares its own minimal structural
:class:`Embedder` Protocol (``async embed(text) -> vector``) rather than
importing the ``EmbeddingModel`` type from ``core/tiers``. The composition
root passes ``container.llm_bindings.embedding_model`` - which satisfies
the structural type - into :class:`EmbeddingKnowledgeSource`.

The upstream default binding is :class:`EmptyKnowledgeSource` (ingest is a
no-op, search returns nothing), so grounding degrades to "no free-form
support -> abstain", never to a fabricated citation. A fork swaps in an
embedding-backed store (in-memory here; a pgvector adapter under
``delivery/`` for production).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

_DEFAULT_MAX_CHARS = 1_200
_DEFAULT_OVERLAP = 150


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """One source document to ingest.

    ``source_ref`` is the citation handle (a URI, a wiki page id, a file
    path) echoed back on every chunk so a grounded answer can point at its
    provenance. ``metadata`` is adapter-neutral and never carries secrets.
    """

    doc_id: str
    text: str
    source_ref: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """One retrieved chunk with its citation and relevance score."""

    doc_id: str
    chunk_id: str
    text: str
    source_ref: str
    score: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class Embedder(Protocol):
    """Structural type for the embedding seam (duck-typed).

    Satisfied by ``core.tiers.t1_lightweight.tier.EmbeddingModel`` and by
    the Azure OpenAI embedding adapter, without this module importing
    either.
    """

    async def embed(self, text: str) -> Sequence[float]: ...


@runtime_checkable
class KnowledgeSource(Protocol):
    """Ingest documents and retrieve grounding chunks by semantic search."""

    async def ingest(self, documents: Sequence[KnowledgeDocument]) -> int:
        """Index ``documents``; return the number of chunks added."""
        ...

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:
        """Return the top-``k`` chunks most relevant to ``query``.

        An empty result is a valid answer (nothing indexed / nothing
        relevant), NOT an error - the grounding caller then abstains.
        """
        ...


class EmptyKnowledgeSource:
    """Upstream default - indexes nothing and retrieves nothing."""

    async def ingest(self, documents: Sequence[KnowledgeDocument]) -> int:  # noqa: ARG002
        return 0

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:  # noqa: ARG002
        return ()


def chunk_text(
    text: str, *, max_chars: int = _DEFAULT_MAX_CHARS, overlap: int = _DEFAULT_OVERLAP
) -> list[str]:
    """Split ``text`` into overlapping fixed-size chunks (deterministic).

    Prefers to break on a paragraph or sentence boundary within the window
    so a chunk does not cut mid-word where avoidable. Overlap preserves
    context across the seam so a fact split across two chunks stays
    retrievable.
    """
    if max_chars <= 0:
        raise ValueError("max_chars MUST be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap MUST be in [0, max_chars)")

    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    n = len(normalized)
    while start < n:
        end = min(start + max_chars, n)
        window = normalized[start:end]
        if end < n:
            # Prefer the last paragraph/sentence break in the window.
            for sep in ("\n\n", "\n", ". ", " "):
                cut = window.rfind(sep)
                if cut > max_chars // 2:
                    end = start + cut + len(sep)
                    window = normalized[start:end]
                    break
        chunk = window.strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors; 0.0 when either is degenerate."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class EmbeddingKnowledgeSource:
    """In-memory embedding-backed knowledge source (reference impl).

    Chunks each document, embeds every chunk through the injected
    :class:`Embedder`, and answers ``search`` by cosine top-k. Backed by a
    plain in-memory list - deterministic and network-free for tests. A
    deployed composition replaces the store with a pgvector adapter under
    ``delivery/`` while keeping this exact :class:`KnowledgeSource`
    contract.
    """

    def __init__(
        self,
        *,
        embedder: Embedder,
        max_chars: int = _DEFAULT_MAX_CHARS,
        overlap: int = _DEFAULT_OVERLAP,
    ) -> None:
        self._embedder = embedder
        self._max_chars = max_chars
        self._overlap = overlap
        # (chunk, vector) pairs.
        self._index: list[tuple[KnowledgeChunk, tuple[float, ...]]] = []

    async def ingest(self, documents: Sequence[KnowledgeDocument]) -> int:
        added = 0
        for doc in documents:
            pieces = chunk_text(doc.text, max_chars=self._max_chars, overlap=self._overlap)
            for i, piece in enumerate(pieces):
                vector = tuple(await self._embedder.embed(piece))
                chunk = KnowledgeChunk(
                    doc_id=doc.doc_id,
                    chunk_id=f"{doc.doc_id}#{i}",
                    text=piece,
                    source_ref=doc.source_ref,
                    metadata=doc.metadata,
                )
                self._index.append((chunk, vector))
                added += 1
        return added

    async def search(self, query: str, *, k: int = 5) -> Sequence[KnowledgeChunk]:
        if k <= 0 or not self._index:
            return ()
        query_vector = tuple(await self._embedder.embed(query))
        scored = [(cosine_similarity(query_vector, vector), chunk) for chunk, vector in self._index]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return tuple(
            KnowledgeChunk(
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                source_ref=chunk.source_ref,
                score=score,
                metadata=chunk.metadata,
            )
            for score, chunk in scored[:k]
        )


def documents_from_texts(pairs: Iterable[tuple[str, str, str]]) -> list[KnowledgeDocument]:
    """Build documents from ``(doc_id, source_ref, text)`` tuples (helper)."""
    return [
        KnowledgeDocument(doc_id=doc_id, source_ref=source_ref, text=text)
        for doc_id, source_ref, text in pairs
    ]


__all__ = [
    "Embedder",
    "EmbeddingKnowledgeSource",
    "EmptyKnowledgeSource",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeSource",
    "chunk_text",
    "cosine_similarity",
    "documents_from_texts",
]
