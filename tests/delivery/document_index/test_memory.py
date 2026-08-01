"""Tests for structure-aware local document indexing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

import pytest

from fdai.delivery.document_index import (
    InMemoryEmbeddingDocumentIndex,
    chunk_document_envelope,
)
from fdai.shared.contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    ProtectionState,
    StructuralUnit,
)

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000101")
_VERSION_ID = UUID("00000000-0000-0000-0000-000000000102")


class _HashEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        vector = [0.0] * 8
        for word in text.lower().split():
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % len(vector)
            vector[bucket] += 1.0
        return vector


class _FailingEmbedder:
    async def embed(self, text: str) -> Sequence[float]:
        raise RuntimeError(f"embedding unavailable for {len(text)} characters")


def _envelope(
    *,
    text: str,
    access_ref: str = "collection:shared-knowledge",
    goal_ref: str | None = None,
) -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id=_DOCUMENT_ID,
        version_id=_VERSION_ID,
        source_sha256="a" * 64,
        media_type="text/plain",
        observed_format="text",
        size_bytes=len(text.encode()),
        collection_id="shared-knowledge",
        purposes=(DocumentPurpose.KNOWLEDGE_BASE,),
        protection_state=ProtectionState.NONE,
        access_descriptor_ref=access_ref,
        units=(
            StructuralUnit(
                unit_id="line-7",
                kind="text",
                locator="line:7",
                text=text,
            ),
        ),
        extractor_name="test",
        extractor_version="1.0.0",
        goal_ref=goal_ref,
    )


def test_chunk_document_envelope_preserves_structural_provenance() -> None:
    records = chunk_document_envelope(
        _envelope(text="alpha beta gamma delta epsilon zeta eta theta"),
        max_chars=24,
        overlap=5,
    )

    assert len(records) > 1
    assert {record.metadata["locator"] for record in records} == {"line:7"}
    assert {record.metadata["access_descriptor_ref"] for record in records} == {
        "collection:shared-knowledge"
    }
    assert {record.metadata["governed_document"] for record in records} == {"true"}
    assert [record.chunk_id.rsplit(":", 1)[-1] for record in records] == [
        str(index) for index in range(len(records))
    ]


def test_handover_chunks_are_deterministic_and_content_addressed() -> None:
    envelope = _envelope(text="heading\nrollback steps", goal_ref="goal-1")

    first = chunk_document_envelope(envelope)
    second = chunk_document_envelope(envelope)

    assert first == second
    assert first[0].metadata["goal_ref"] == "goal-1"
    assert first[0].metadata["chunk_policy_version"] == "structure-aware-v1"
    assert first[0].metadata["content_digest"] == hashlib.sha256(first[0].text.encode()).hexdigest()
    span = json.loads(first[0].metadata["source_span"])
    assert span["unit_id"] == "line-7"
    assert span["locator"] == "line:7"


async def test_in_memory_index_searches_only_authorized_collection() -> None:
    index = InMemoryEmbeddingDocumentIndex(embedder=_HashEmbedder())
    assert await index.commit(_envelope(text="disk full clear old logs")) == 1

    denied = await index.search(
        "disk full",
        collection_id="shared-knowledge",
        allowed_access_refs=frozenset({"collection:other"}),
    )
    hits = await index.search(
        "disk full",
        collection_id="shared-knowledge",
        allowed_access_refs=frozenset({"collection:shared-knowledge"}),
    )

    assert denied == ()
    assert len(hits) == 1
    assert hits[0].metadata["locator"] == "line:7"


async def test_in_memory_index_recommit_replaces_and_delete_removes_version() -> None:
    index = InMemoryEmbeddingDocumentIndex(embedder=_HashEmbedder())
    await index.commit(_envelope(text="old content"))
    await index.commit(_envelope(text="replacement content"))

    hits = await index.search(
        "replacement",
        collection_id="shared-knowledge",
        allowed_access_refs=frozenset({"collection:shared-knowledge"}),
    )
    assert [hit.text for hit in hits] == ["replacement content"]

    await index.delete(_DOCUMENT_ID, _VERSION_ID)
    assert (
        await index.search(
            "replacement",
            collection_id="shared-knowledge",
            allowed_access_refs=frozenset({"collection:shared-knowledge"}),
        )
        == ()
    )


async def test_in_memory_index_embedding_failure_keeps_existing_version() -> None:
    index = InMemoryEmbeddingDocumentIndex(embedder=_HashEmbedder())
    await index.commit(_envelope(text="known good content"))
    index._embedder = _FailingEmbedder()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await index.commit(_envelope(text="replacement content"))

    index._embedder = _HashEmbedder()  # type: ignore[assignment]
    hits = await index.search(
        "known good",
        collection_id="shared-knowledge",
        allowed_access_refs=frozenset({"collection:shared-knowledge"}),
    )
    assert [hit.text for hit in hits] == ["known good content"]
