"""Free-form document evidence gathering for RCA grounding.

The counterpart of :class:`~fdai.core.rca.evidence.TelemetryEvidenceGatherer`
for the **free-form knowledge** leg. Where the telemetry gatherer grounds a
hypothesis on error logs / spans, this one grounds it on the operator's
ingested documents - runbooks, architecture notes, and **resource plans** -
via the :class:`~fdai.shared.providers.knowledge.KnowledgeSource` seam.

This is the consumer the Knowledge Base ingestion path was missing: FDAI
already chunks + embeds + indexes uploaded documents
(:class:`~fdai.shared.providers.knowledge.EmbeddingKnowledgeSource` /
``PgvectorKnowledgeSource``), but nothing turned a retrieved chunk into a
grounded RCA :class:`~fdai.core.rca.contract.Citation`. A document an
operator uploads is therefore now actually referenced when the T2 reasoner
forms a hypothesis: a relevant chunk becomes a
``CitationKind.KNOWLEDGE`` candidate the reasoner may cite, and the
grounding gate refuses any citation not in that vouched-for set.

Fail-safe by construction (matches the seam's "empty result is a valid
answer" contract): an unbound source, an empty index, or a provider
outage contributes **no** citations rather than raising. Empty evidence
then makes the grounding gate abstain to HIL - the control plane never
reasons on the absence of a document.

Secret-safe: a citation ``ref`` is the opaque
``knowledge:<source_ref>#<chunk_id>`` handle. ``source_ref`` is the
document's declared citation handle (a wiki id, a file path, a URI) which
by contract "never carries secrets"; the chunk body text is never placed
in a citation, audit entry, or model prompt.

CSP-neutral: imports only the ``KnowledgeSource`` Protocol and the RCA
contract, so it stays under the ``core/`` import rule.
"""

from __future__ import annotations

import logging

from fdai.core.rca.contract import Citation, CitationKind
from fdai.shared.providers.knowledge import KnowledgeChunk, KnowledgeSource

_LOGGER = logging.getLogger(__name__)


def _knowledge_ref(chunk: KnowledgeChunk) -> str:
    """Opaque provenance handle for a retrieved chunk (no body text)."""
    return f"knowledge:{chunk.source_ref}#{chunk.chunk_id}"


class KnowledgeEvidenceGatherer:
    """Gather KNOWLEDGE citations for RCA from the free-form document seam."""

    __slots__ = ("_min_score", "_source", "_top_k")

    def __init__(
        self,
        *,
        source: KnowledgeSource | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k MUST be >= 1")
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score MUST be in [0, 1]")
        self._source = source
        self._top_k = top_k
        self._min_score = min_score

    @property
    def is_bound(self) -> bool:
        """True iff a knowledge source is configured."""
        return self._source is not None

    async def gather(self, *, query: str, limit: int | None = None) -> tuple[Citation, ...]:
        """Return KNOWLEDGE citations for documents relevant to ``query``.

        Searches the bound :class:`KnowledgeSource` for the top-``k`` most
        relevant chunks, keeps those at or above ``min_score``, and maps each
        to an opaque :class:`Citation`. Deduplicates by ref and preserves
        relevance order. Never raises: an unbound source, an empty query, or a
        provider outage yields ``()`` so the grounding gate abstains rather
        than reasoning on nothing.
        """
        if self._source is None:
            return ()
        if not query.strip():
            return ()

        k = self._top_k if limit is None else max(1, min(limit, self._top_k))
        try:
            chunks = await self._source.search(query, k=k)
        except Exception:  # noqa: BLE001 - fail closed: a source outage grounds nothing
            _LOGGER.warning(
                "knowledge source search failed; contributing no citations",
                exc_info=True,
            )
            return ()

        citations: list[Citation] = []
        seen: set[str] = set()
        for chunk in chunks:
            if chunk.score < self._min_score:
                continue
            ref = _knowledge_ref(chunk)
            if ref in seen:
                continue
            seen.add(ref)
            citations.append(Citation(kind=CitationKind.KNOWLEDGE, ref=ref))
        return tuple(citations)


__all__ = [
    "KnowledgeEvidenceGatherer",
]
