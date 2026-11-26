"""SummarizationOrchestrator - execute the fold plan via the summarizer seam.

:func:`~fdai.core.working_context.planner.plan_summarization` decides *what*
to fold (pure policy); :class:`~fdai.core.working_context.summarizer.TranscriptSummarizer`
knows *how* to fold one span (async seam). This orchestrator connects them:
it plans, runs each :class:`~fdai.core.working_context.planner.FoldPlan`
through the summarizer, and returns the newly produced summary entries for
the caller to append to the memory of record.

It runs off the hot path (a background compaction step after a turn), so a
turn's latency is never blocked on summarization. A single ``fold`` call
produces at most one level per span; a freshly produced level-1 summary is
only eligible for a level-2 fold on the *next* call (the planner reads the
summaries that already exist), which keeps folding incremental and stable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fdai.core.working_context.planner import plan_summarization
from fdai.core.working_context.summarizer import TranscriptSummarizer
from fdai.core.working_context.types import TranscriptEntry


class SummarizationOrchestrator:
    """Plan + execute hierarchical folds over a transcript."""

    def __init__(
        self,
        *,
        summarizer: TranscriptSummarizer,
        fold_factor: int = 4,
    ) -> None:
        if fold_factor < 2:
            raise ValueError("fold_factor MUST be >= 2")
        self._summarizer: Final[TranscriptSummarizer] = summarizer
        self._fold_factor: Final[int] = fold_factor

    async def fold(
        self,
        *,
        verbatim: Sequence[TranscriptEntry],
        existing_summaries: Sequence[TranscriptEntry],
        verbatim_budget: int,
    ) -> tuple[TranscriptEntry, ...]:
        """Run every planned fold and return the new summary entries.

        Returns ``()`` when nothing needs folding. The caller appends the
        result to the lossless memory of record and passes it back as
        ``existing_summaries`` on the next call so higher levels can form.
        """

        plans = plan_summarization(
            verbatim=verbatim,
            existing_summaries=existing_summaries,
            verbatim_budget=verbatim_budget,
            fold_factor=self._fold_factor,
        )
        if not plans:
            return ()

        index: dict[str, TranscriptEntry] = {
            e.entry_id: e for e in (*verbatim, *existing_summaries)
        }
        produced: list[TranscriptEntry] = []
        for plan in plans:
            try:
                span = [index[source_id] for source_id in plan.source_ids]
            except KeyError as exc:
                raise ValueError(f"fold plan references an unknown entry id: {exc}") from exc
            summary = await self._summarizer.summarize(entries=span, level=plan.level)
            produced.append(summary)
            index[summary.entry_id] = summary
        return tuple(produced)


__all__ = ["SummarizationOrchestrator"]
