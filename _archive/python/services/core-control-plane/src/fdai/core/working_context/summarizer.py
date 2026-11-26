"""Working-context I/O seams: summarize + retrieve.

These are the two ``async`` provider Protocols the composition root wires
so the pure :func:`~fdai.core.working_context.composer.compose_working_context`
policy has hierarchical summaries and relevance-retrieved snippets to
choose from. ``core/`` depends only on the Protocols; the real
implementations (a mini-model summarizer, a pgvector retriever) live in
the delivery layer.

- :class:`TranscriptSummarizer` folds a span of older entries into one
  higher-level :class:`~fdai.core.working_context.types.TranscriptEntry`
  of kind ``SUMMARY``. Hierarchical folding (level 1 folds turns, level 2
  folds level-1 summaries) is what keeps the summary tier ``O(log L)``.
- :class:`TranscriptRetriever` selects the entries most relevant to the
  current utterance so a turn that fell outside the verbatim window can
  still return to the prompt when it matters.

Upstream ships deterministic, no-LLM fakes so tests and a dev harness run
without a provider wired - the same deny-by-default posture as
:class:`~fdai.core.web_search.provider.NoOpWebSearchProvider`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from fdai.core.working_context.types import (
    EntryKind,
    EntryRole,
    TranscriptEntry,
)


def _estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate for the fakes (~4 chars/token).

    Real adapters use the provider tokenizer; the fakes only need a
    stable, monotone estimate so composer tests are reproducible.
    """

    return max(1, len(text) // 4)


@runtime_checkable
class TranscriptSummarizer(Protocol):
    """Fold a span of entries into one higher-level summary entry.

    ``level`` is the summary level to produce (>= 1). The returned entry
    MUST carry ``kind=SUMMARY``, ``source_ids`` naming every folded
    entry, and ``trusted=False`` unless every folded entry was trusted
    (a summary of untrusted content stays untrusted data).
    """

    async def summarize(
        self,
        *,
        entries: Sequence[TranscriptEntry],
        level: int,
    ) -> TranscriptEntry: ...


@runtime_checkable
class TranscriptRetriever(Protocol):
    """Select the entries most relevant to the current utterance.

    Implementations embed ``utterance`` and score it against
    ``candidates`` (a vector store in production), returning at most
    ``k`` entries with ``relevance`` populated in ``[0.0, 1.0]``. The
    returned entries keep their original ``kind`` so the composer still
    budgets them in the retrieval tier.
    """

    async def retrieve(
        self,
        *,
        utterance: str,
        candidates: Sequence[TranscriptEntry],
        k: int,
    ) -> Sequence[TranscriptEntry]: ...


class DeterministicTruncationSummarizer(TranscriptSummarizer):
    """No-LLM summarizer fake: concatenate + truncate.

    Produces a stable, dependency-free summary so composer / pipeline
    tests run without a model. It joins the folded entries' text, caps
    it at ``max_chars``, and records provenance. Not a production
    summarizer - a real adapter calls the ``t1.judge`` mini model.
    """

    def __init__(self, *, max_chars: int = 512) -> None:
        if max_chars < 1:
            raise ValueError("max_chars MUST be >= 1")
        self._max_chars = max_chars

    async def summarize(
        self,
        *,
        entries: Sequence[TranscriptEntry],
        level: int,
    ) -> TranscriptEntry:
        if not entries:
            raise ValueError("cannot summarize an empty span")
        if level < 1:
            raise ValueError("summary level MUST be >= 1")
        joined = " | ".join(e.text for e in entries)[: self._max_chars]
        newest = max(entries, key=lambda e: e.sequence)
        return TranscriptEntry(
            entry_id=f"sum-l{level}-{newest.entry_id}",
            role=EntryRole.SYSTEM,
            kind=EntryKind.SUMMARY,
            text=joined,
            tokens=_estimate_tokens(joined),
            sequence=newest.sequence,
            trusted=all(e.trusted for e in entries),
            level=level,
            source_ids=tuple(e.entry_id for e in entries),
        )


class NoOpRetriever(TranscriptRetriever):
    """Deny-by-default retriever: returns zero snippets.

    The composer then relies purely on the verbatim + summary tiers,
    exactly as if no vector store were wired. A fork swaps in a pgvector
    retriever at the composition root.
    """

    async def retrieve(
        self,
        *,
        utterance: str,
        candidates: Sequence[TranscriptEntry],
        k: int,
    ) -> Sequence[TranscriptEntry]:
        return ()


__all__ = [
    "DeterministicTruncationSummarizer",
    "NoOpRetriever",
    "TranscriptRetriever",
    "TranscriptSummarizer",
]
