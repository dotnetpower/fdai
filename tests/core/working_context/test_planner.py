"""Tests for :mod:`fdai.core.working_context.planner`."""

from __future__ import annotations

import pytest

from fdai.core.working_context.planner import FoldPlan, plan_summarization
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


def _summary(
    entry_id: str, *, sequence: int, level: int, source_ids: tuple[str, ...]
) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=entry_id,
        role=EntryRole.SYSTEM,
        kind=EntryKind.SUMMARY,
        text="summary",
        tokens=8,
        sequence=sequence,
        level=level,
        source_ids=source_ids,
    )


def test_no_fold_when_all_turns_fit_window() -> None:
    turns = [_turn(f"t{i}", sequence=i) for i in range(3)]
    plans = plan_summarization(
        verbatim=turns, existing_summaries=[], verbatim_budget=1000, fold_factor=4
    )
    assert plans == ()


def test_out_of_window_turns_fold_into_level1_chunks() -> None:
    # 10 turns, budget keeps ~2 newest (20 tokens); 8 remain, fold_factor 4
    # -> two full level-1 chunks.
    turns = [_turn(f"t{i}", sequence=i, tokens=10) for i in range(10)]
    plans = plan_summarization(
        verbatim=turns, existing_summaries=[], verbatim_budget=20, fold_factor=4
    )
    assert len(plans) == 2
    assert all(p.level == 1 for p in plans)
    # Oldest first.
    assert plans[0].source_ids == ("t0", "t1", "t2", "t3")
    assert plans[1].source_ids == ("t4", "t5", "t6", "t7")


def test_partial_chunk_waits() -> None:
    # 6 out-of-window turns, fold_factor 4 -> only one full chunk; the
    # trailing 2 wait for more turns.
    turns = [_turn(f"t{i}", sequence=i, tokens=10) for i in range(7)]
    plans = plan_summarization(
        verbatim=turns, existing_summaries=[], verbatim_budget=10, fold_factor=4
    )
    l1 = [p for p in plans if p.level == 1]
    assert len(l1) == 1
    assert l1[0].source_ids == ("t0", "t1", "t2", "t3")


def test_already_covered_turns_not_refolded() -> None:
    turns = [_turn(f"t{i}", sequence=i, tokens=10) for i in range(8)]
    existing = [_summary("s1", sequence=3, level=1, source_ids=("t0", "t1", "t2", "t3"))]
    plans = plan_summarization(
        verbatim=turns, existing_summaries=existing, verbatim_budget=0, fold_factor=4
    )
    # t0-t3 already folded; only t4-t7 remain as a fresh chunk.
    l1 = [p for p in plans if p.level == 1]
    assert len(l1) == 1
    assert l1[0].source_ids == ("t4", "t5", "t6", "t7")


def test_level1_summaries_fold_into_level2() -> None:
    # Four level-1 summaries and no pending verbatim -> one level-2 fold.
    summaries = [_summary(f"s{i}", sequence=i, level=1, source_ids=(f"t{i}",)) for i in range(4)]
    plans = plan_summarization(
        verbatim=[], existing_summaries=summaries, verbatim_budget=0, fold_factor=4
    )
    l2 = [p for p in plans if p.level == 2]
    assert len(l2) == 1
    assert l2[0].source_ids == ("s0", "s1", "s2", "s3")


def test_level1_summaries_covered_by_level2_not_refolded() -> None:
    summaries = [_summary(f"s{i}", sequence=i, level=1, source_ids=(f"t{i}",)) for i in range(4)]
    summaries.append(_summary("L2", sequence=10, level=2, source_ids=("s0", "s1", "s2", "s3")))
    plans = plan_summarization(
        verbatim=[], existing_summaries=summaries, verbatim_budget=0, fold_factor=4
    )
    assert plans == ()


def test_logarithmic_growth_bound() -> None:
    # A long session, folded once, keeps far fewer summaries than turns.
    turns = [_turn(f"t{i}", sequence=i, tokens=10) for i in range(100)]
    plans = plan_summarization(
        verbatim=turns, existing_summaries=[], verbatim_budget=20, fold_factor=4
    )
    # ~98 out-of-window turns / 4 = 24 level-1 folds, not 98.
    assert all(p.level == 1 for p in plans)
    assert len(plans) == 24


def test_fold_factor_must_be_at_least_two() -> None:
    with pytest.raises(ValueError, match="fold_factor"):
        plan_summarization(verbatim=[], existing_summaries=[], verbatim_budget=0, fold_factor=1)


def test_returns_foldplan_type() -> None:
    turns = [_turn(f"t{i}", sequence=i, tokens=10) for i in range(8)]
    plans = plan_summarization(
        verbatim=turns, existing_summaries=[], verbatim_budget=10, fold_factor=4
    )
    assert all(isinstance(p, FoldPlan) for p in plans)
