"""plan_summarization - the pure policy that drives hierarchical folding.

The composer (:mod:`fdai.core.working_context.composer`) *consumes* summary
entries but does not decide which turns to fold or when. This module is
that missing policy: given the verbatim turns, the summaries that already
exist, and the verbatim token budget, it returns the fold operations
needed so the summary tier stays ``O(log L)`` in session length ``L``.

It is a pure, deterministic function (no I/O - the actual folding is the
async :class:`~fdai.core.working_context.summarizer.TranscriptSummarizer`
seam). An orchestrator calls :func:`plan_summarization`, executes each
:class:`FoldPlan` via the summarizer, appends the results to the memory of
record, and re-plans on the next turn. Because level-1 folds groups of
turns and level-2 folds groups of level-1 summaries, the number of
summaries kept grows logarithmically, not linearly.

Design reference:
- ``docs/roadmap/interfaces/operator-console.md`` section 6.4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdai.core.working_context.types import EntryKind, TranscriptEntry


@dataclass(frozen=True, slots=True)
class FoldPlan:
    """One fold the summarizer should perform.

    ``level`` is the summary level to produce (1 folds verbatim turns, 2
    folds level-1 summaries, ...). ``source_ids`` are the entry ids to fold,
    oldest first. The orchestrator passes the matching entries to
    :meth:`TranscriptSummarizer.summarize`.
    """

    level: int
    source_ids: tuple[str, ...]


def _covered_source_ids(summaries: Sequence[TranscriptEntry], *, min_level: int) -> set[str]:
    covered: set[str] = set()
    for summary in summaries:
        if summary.level >= min_level:
            covered.update(summary.source_ids)
    return covered


def plan_summarization(
    *,
    verbatim: Sequence[TranscriptEntry],
    existing_summaries: Sequence[TranscriptEntry],
    verbatim_budget: int,
    fold_factor: int = 4,
) -> tuple[FoldPlan, ...]:
    """Return the fold operations that keep the summary tier bounded.

    - **Keep window**: the newest verbatim turns that fit ``verbatim_budget``
      stay verbatim and are never folded.
    - **Level 1**: verbatim turns outside the keep window and not already
      covered by a summary are grouped oldest-first into full chunks of
      ``fold_factor``; a partial trailing chunk waits for more turns.
    - **Level 2+**: level-1 summaries not yet covered by a higher summary are
      likewise grouped into chunks of ``fold_factor``.

    Only *full* chunks are planned, so folding is stable (a turn is never
    folded alone then re-folded) and the tier count is ``O(log L)``.
    """

    if fold_factor < 2:
        raise ValueError("fold_factor MUST be >= 2")
    if verbatim_budget < 0:
        raise ValueError("verbatim_budget MUST be >= 0")

    # 1. Keep window: fill the budget newest-first; the rest are candidates.
    kept: set[str] = set()
    used = 0
    for entry in sorted(verbatim, key=lambda e: -e.sequence):
        if used + entry.tokens <= verbatim_budget:
            kept.add(entry.entry_id)
            used += entry.tokens

    plans: list[FoldPlan] = []

    # 2. Level-1 folds over uncovered, out-of-window verbatim turns.
    covered_l1 = _covered_source_ids(existing_summaries, min_level=1)
    l1_candidates = [
        e
        for e in sorted(verbatim, key=lambda e: e.sequence)
        if e.entry_id not in kept and e.entry_id not in covered_l1
    ]
    plans.extend(_chunk_plans(l1_candidates, level=1, fold_factor=fold_factor))

    # 3. Level-2 folds over uncovered level-1 summaries.
    covered_l2 = _covered_source_ids(existing_summaries, min_level=2)
    l1_summaries = sorted(
        (
            s
            for s in existing_summaries
            if s.kind is EntryKind.SUMMARY and s.level == 1 and s.entry_id not in covered_l2
        ),
        key=lambda s: s.sequence,
    )
    plans.extend(_chunk_plans(l1_summaries, level=2, fold_factor=fold_factor))

    return tuple(plans)


def _chunk_plans(
    items: Sequence[TranscriptEntry], *, level: int, fold_factor: int
) -> list[FoldPlan]:
    plans: list[FoldPlan] = []
    full_chunks = len(items) // fold_factor
    for i in range(full_chunks):
        chunk = items[i * fold_factor : (i + 1) * fold_factor]
        plans.append(FoldPlan(level=level, source_ids=tuple(e.entry_id for e in chunk)))
    return plans


__all__ = ["FoldPlan", "plan_summarization"]
