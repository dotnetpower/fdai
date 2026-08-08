"""Unit tests for :mod:`fdai.core.working_context`."""

from __future__ import annotations

import pytest
from fdai.core.working_context import (
    ContextBudget,
    DeterministicTruncationSummarizer,
    EntryKind,
    EntryRole,
    NoOpRetriever,
    TranscriptEntry,
    WorkingContextError,
    compose_working_context,
)


def _entry(
    entry_id: str,
    *,
    kind: EntryKind = EntryKind.VERBATIM,
    tokens: int = 10,
    sequence: int = 0,
    pinned: bool = False,
    trusted: bool = False,
    level: int = 0,
    relevance: float | None = None,
) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=entry_id,
        role=EntryRole.OPERATOR,
        kind=kind,
        text=f"text-{entry_id}",
        tokens=tokens,
        sequence=sequence,
        pinned=pinned,
        trusted=trusted,
        level=level,
        relevance=relevance,
    )


def _budget(history: int, **ratios: float) -> ContextBudget:
    """A budget whose history_budget == ``history`` (all reserves zero)."""

    return ContextBudget(
        total_window=history + 1,
        base_reserve=0,
        output_reserve=1,
        tools_reserve=0,
        memory_reserve=0,
        **ratios,
    )


# --------------------------------------------------------------------------
# ContextBudget validation
# --------------------------------------------------------------------------


def test_context_budget_history_is_window_minus_reserves() -> None:
    budget = ContextBudget(
        total_window=1000,
        base_reserve=100,
        output_reserve=200,
        tools_reserve=50,
        memory_reserve=50,
    )
    assert budget.history_budget == 600


def test_context_budget_rejects_ratio_sum_over_one() -> None:
    with pytest.raises(ValueError, match="sum to <= 1.0"):
        ContextBudget(
            verbatim_ratio=0.5, retrieval_ratio=0.4, summary_ratio=0.3, typed_fact_ratio=0.2
        )


def test_context_budget_rejects_reserves_exceeding_window() -> None:
    with pytest.raises(ValueError, match="no room for history"):
        ContextBudget(total_window=100, base_reserve=100, output_reserve=100)


# --------------------------------------------------------------------------
# compose_working_context - budget & priority
# --------------------------------------------------------------------------


def test_all_entries_fit_when_budget_is_ample() -> None:
    entries = [_entry(f"v{i}", sequence=i, tokens=10) for i in range(5)]
    ctx = compose_working_context(budget=_budget(1000), entries=entries)
    assert set(ctx.manifest.verbatim_ids) == {f"v{i}" for i in range(5)}
    assert ctx.manifest.dropped_ids == ()
    assert ctx.total_tokens == 50


def test_bounded_growth_regardless_of_session_length() -> None:
    # 1000 turns, tiny budget: the projection stays under the history cap
    # even though the "memory of record" (entries) is O(L).
    entries = [_entry(f"v{i}", sequence=i, tokens=10) for i in range(1000)]
    budget = _budget(
        100, verbatim_ratio=1.0, retrieval_ratio=0.0, summary_ratio=0.0, typed_fact_ratio=0.0
    )
    ctx = compose_working_context(budget=budget, entries=entries)
    assert ctx.total_tokens <= 100
    # newest turns win (verbatim is newest-first).
    assert "v999" in ctx.manifest.verbatim_ids
    assert "v0" not in ctx.manifest.verbatim_ids
    assert len(ctx.manifest.dropped_ids) == 990


def test_newest_verbatim_preferred_under_pressure() -> None:
    entries = [_entry(f"v{i}", sequence=i, tokens=10) for i in range(5)]
    budget = _budget(
        20, verbatim_ratio=1.0, retrieval_ratio=0.0, summary_ratio=0.0, typed_fact_ratio=0.0
    )
    ctx = compose_working_context(budget=budget, entries=entries)
    assert set(ctx.manifest.verbatim_ids) == {"v3", "v4"}


def test_pinned_always_included_before_budget() -> None:
    entries = [
        _entry("pin", pinned=True, tokens=10, sequence=0),
        *[_entry(f"v{i}", sequence=i + 1, tokens=10) for i in range(5)],
    ]
    budget = _budget(
        20, verbatim_ratio=1.0, retrieval_ratio=0.0, summary_ratio=0.0, typed_fact_ratio=0.0
    )
    ctx = compose_working_context(budget=budget, entries=entries)
    assert "pin" in ctx.manifest.pinned_ids
    # 10 tokens for the pin leaves 10 for exactly one verbatim (newest = v4,
    # sequence 5).
    assert ctx.manifest.verbatim_ids == ("v4",)


def test_pinned_overflow_fails_closed() -> None:
    entries = [_entry("pin", pinned=True, tokens=200)]
    with pytest.raises(WorkingContextError, match="pinned entries exceed"):
        compose_working_context(budget=_budget(100), entries=entries)


def test_typed_facts_preferred_over_summaries() -> None:
    entries = [
        _entry("t0", kind=EntryKind.TYPED_FACT, trusted=True, sequence=1, tokens=10),
        _entry("s1", kind=EntryKind.SUMMARY, level=1, sequence=0, tokens=10),
    ]
    # Budget fits only one entry; typed fact wins its tier.
    budget = _budget(
        10,
        verbatim_ratio=0.0,
        retrieval_ratio=0.0,
        summary_ratio=0.0,
        typed_fact_ratio=1.0,
    )
    ctx = compose_working_context(budget=budget, entries=entries)
    assert ctx.manifest.typed_fact_ids == ("t0",)
    assert ctx.manifest.summary_ids == ()


def test_retrieved_dedup_against_verbatim() -> None:
    # Same entry id appears as both verbatim and retrieved; counted once.
    entries = [
        _entry("shared", kind=EntryKind.VERBATIM, sequence=5, tokens=10),
        _entry("shared", kind=EntryKind.RETRIEVED, sequence=5, tokens=10, relevance=0.9),
    ]
    ctx = compose_working_context(budget=_budget(1000), entries=entries)
    all_ids = ctx.manifest.verbatim_ids + ctx.manifest.retrieved_ids
    assert all_ids.count("shared") == 1


def test_retrieval_orders_by_relevance() -> None:
    entries = [
        _entry("r_low", kind=EntryKind.RETRIEVED, sequence=1, tokens=10, relevance=0.2),
        _entry("r_high", kind=EntryKind.RETRIEVED, sequence=2, tokens=10, relevance=0.95),
    ]
    budget = _budget(
        10,
        verbatim_ratio=0.0,
        retrieval_ratio=1.0,
        summary_ratio=0.0,
        typed_fact_ratio=0.0,
    )
    ctx = compose_working_context(budget=budget, entries=entries)
    assert ctx.manifest.retrieved_ids == ("r_high",)


def test_prompt_order_pinned_first_verbatim_last() -> None:
    entries = [
        _entry("v_old", kind=EntryKind.VERBATIM, sequence=1, tokens=5),
        _entry("v_new", kind=EntryKind.VERBATIM, sequence=9, tokens=5),
        _entry("sum", kind=EntryKind.SUMMARY, level=1, sequence=0, tokens=5),
        _entry("pin", pinned=True, sequence=2, tokens=5),
    ]
    ctx = compose_working_context(budget=_budget(1000), entries=entries)
    order = [e.entry_id for e in ctx.entries]
    assert order[0] == "pin"
    assert order[-1] == "v_new"
    assert order.index("sum") < order.index("v_old")


def test_spill_lets_verbatim_use_unused_typed_budget() -> None:
    # No typed facts; verbatim ratio small but should spill from typed.
    entries = [_entry(f"v{i}", sequence=i, tokens=10) for i in range(10)]
    budget = _budget(
        100,
        verbatim_ratio=0.5,
        retrieval_ratio=0.0,
        summary_ratio=0.0,
        typed_fact_ratio=0.5,
    )
    ctx = compose_working_context(budget=budget, entries=entries)
    # typed budget (50) is unused and spills to verbatim (50) => 100 total.
    assert ctx.total_tokens == 100
    assert len(ctx.manifest.verbatim_ids) == 10


# --------------------------------------------------------------------------
# Seam fakes
# --------------------------------------------------------------------------


async def test_deterministic_summarizer_folds_span() -> None:
    summarizer = DeterministicTruncationSummarizer(max_chars=64)
    span = [
        _entry("a", sequence=1, trusted=True),
        _entry("b", sequence=2, trusted=True),
    ]
    summary = await summarizer.summarize(entries=span, level=1)
    assert summary.kind is EntryKind.SUMMARY
    assert summary.level == 1
    assert summary.source_ids == ("a", "b")
    assert summary.trusted is True
    assert summary.sequence == 2


async def test_summary_untrusted_when_any_source_untrusted() -> None:
    summarizer = DeterministicTruncationSummarizer()
    span = [
        _entry("a", sequence=1, trusted=True),
        _entry("b", sequence=2, trusted=False),
    ]
    summary = await summarizer.summarize(entries=span, level=1)
    assert summary.trusted is False


async def test_noop_retriever_returns_nothing() -> None:
    retriever = NoOpRetriever()
    got = await retriever.retrieve(utterance="q", candidates=[_entry("a")], k=3)
    assert got == ()
