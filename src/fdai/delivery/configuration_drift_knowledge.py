"""Exact-version DOCX ingestion for frozen configuration baselines."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from fdai.core.detection.configuration_drift import FrozenConfigurationBaseline
from fdai.shared.providers.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    chunk_text,
)
from fdai.shared.providers.local.document_structure import extract_ooxml

_MAX_DOCUMENT_BYTES: Final[int] = 16 * 1024 * 1024
_SEARCH_TERM: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,}")


class PinnedConfigurationBaselineKnowledgeSource:
    """Exact single-document retrieval for one integrity-pinned baseline."""

    def __init__(self, document: KnowledgeDocument) -> None:
        self._document = document
        self._chunks = tuple(chunk_text(document.text))

    async def ingest(self, documents: Sequence[KnowledgeDocument]) -> int:
        if tuple(documents) != (self._document,):
            raise ValueError("pinned configuration baseline cannot be replaced")
        return len(self._chunks)

    async def search(self, query: str, *, k: int = 5) -> tuple[KnowledgeChunk, ...]:
        document_sha256 = self._document.metadata["document_sha256"]
        expected = (
            self._document.doc_id.casefold(),
            self._document.source_ref.casefold(),
            self._document.metadata.get("baseline_version", "").casefold(),
            self._document.metadata.get("document_sha256", "").casefold(),
        )
        normalized = query.casefold()
        exact_match = any(token and token in normalized for token in expected)
        query_terms = _terms(normalized)
        ranked = sorted(
            (
                (_relevance(query_terms, text), index, text)
                for index, text in enumerate(self._chunks)
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if not exact_match and (not ranked or ranked[0][0] < 2):
            return ()
        return tuple(
            KnowledgeChunk(
                doc_id=self._document.doc_id,
                chunk_id=f"{self._document.doc_id}#{document_sha256}#{index}",
                text=text,
                source_ref=self._document.source_ref,
                score=1.0 + score if exact_match else score / max(1, len(query_terms)),
                metadata=self._document.metadata,
            )
            for score, index, text in ranked[:k]
        )


def _terms(text: str) -> frozenset[str]:
    return frozenset(match.group(0).casefold() for match in _SEARCH_TERM.finditer(text))


def _relevance(query_terms: frozenset[str], text: str) -> int:
    return len(query_terms.intersection(_terms(text)))


def configuration_baseline_document(
    baseline: FrozenConfigurationBaseline,
    *,
    document_path: Path,
) -> KnowledgeDocument:
    """Build one host-path-free Knowledge document pinned to baseline metadata."""

    content = document_path.read_bytes()
    if not content or len(content) > _MAX_DOCUMENT_BYTES:
        raise ValueError("configuration baseline DOCX size is outside the allowed range")
    digest = hashlib.sha256(content).hexdigest()
    if digest != baseline.document_sha256:
        raise ValueError("configuration baseline DOCX digest does not match the baseline")
    units = extract_ooxml(content)
    text = "\n\n".join(unit.text for unit in units if unit.text.strip())
    if not text:
        raise ValueError("configuration baseline DOCX contains no readable content")
    source_ref = document_path.name
    return KnowledgeDocument(
        doc_id=f"configuration-baseline:{baseline.version}",
        text=text,
        source_ref=source_ref,
        metadata={
            "baseline_version": baseline.version,
            "baseline_sha256": baseline.sha256,
            "document_sha256": baseline.document_sha256,
            "scope": baseline.scope,
            "suffix": ".docx",
        },
    )


async def ingest_configuration_baseline(
    source: KnowledgeSource,
    baseline: FrozenConfigurationBaseline,
    *,
    document_path: Path,
) -> int:
    """Ingest one exact baseline and fail when no chunk is accepted."""

    document = configuration_baseline_document(baseline, document_path=document_path)
    added = await source.ingest((document,))
    if added < 1:
        raise RuntimeError("configuration baseline Knowledge ingestion added no chunks")
    return added


__all__ = [
    "PinnedConfigurationBaselineKnowledgeSource",
    "configuration_baseline_document",
    "ingest_configuration_baseline",
]
