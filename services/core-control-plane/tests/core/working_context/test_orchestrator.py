"""Tests for :mod:`fdai.core.working_context.orchestrator`."""

from __future__ import annotations

import pytest
from fdai.core.working_context.orchestrator import SummarizationOrchestrator
from fdai.core.working_context.summarizer import DeterministicTruncationSummarizer
from fdai.core.working_context.types import EntryKind, EntryRole, TranscriptEntry


def _turn(entry_id: str, *, sequence: int, tokens: int = 10) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=entry_id,
        role=EntryRole.OPERATOR,
        kind=EntryKind.VERBATIM,
        text=f"turn {entry_id}",
        tokens=tokens,
        sequence=sequence,
    )


def _orch() -> SummarizationOrchestrator:
    return SummarizationOrchestrator(summarizer=DeterministicTruncationSummarizer(), fold_factor=4)


async def test_fold_produces_level1_summaries() -> None:
    verbatim = [_turn(f"t{i}", sequence=i) for i in range(8)]
    produced = await _orch().fold(verbatim=verbatim, existing_summaries=[], verbatim_budget=0)
    assert len(produced) == 2
    assert all(s.kind is EntryKind.SUMMARY and s.level == 1 for s in produced)
    assert produced[0].source_ids == ("t0", "t1", "t2", "t3")
    assert produced[1].source_ids == ("t4", "t5", "t6", "t7")


async def test_no_fold_returns_empty() -> None:
    verbatim = [_turn(f"t{i}", sequence=i) for i in range(3)]
    produced = await _orch().fold(verbatim=verbatim, existing_summaries=[], verbatim_budget=1000)
    assert produced == ()


async def test_incremental_level2_on_second_call() -> None:
    orch = _orch()
    verbatim = [_turn(f"t{i}", sequence=i) for i in range(16)]
    # First call folds 16 turns into four level-1 summaries.
    level1 = await orch.fold(verbatim=verbatim, existing_summaries=[], verbatim_budget=0)
    assert len(level1) == 4
    # Second call: the four level-1 summaries now fold into one level-2.
    level2 = await orch.fold(verbatim=verbatim, existing_summaries=list(level1), verbatim_budget=0)
    l2 = [s for s in level2 if s.level == 2]
    assert len(l2) == 1
    assert l2[0].source_ids == tuple(s.entry_id for s in level1)


def test_fold_factor_validation() -> None:
    with pytest.raises(ValueError, match="fold_factor"):
        SummarizationOrchestrator(summarizer=DeterministicTruncationSummarizer(), fold_factor=1)
