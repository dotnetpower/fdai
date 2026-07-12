"""Tests for :mod:`fdai.core.conversation.context_bridge`."""

from __future__ import annotations

from fdai.core.conversation.context_bridge import session_to_working_context
from fdai.core.conversation.session import (
    ConversationSession,
    Principal,
    Role,
    Turn,
)
from fdai.core.working_context.types import (
    ContextBudget,
    EntryKind,
    EntryRole,
    TranscriptEntry,
)


def _session(*contents: str) -> ConversationSession:
    session = ConversationSession(
        session_id="s1",
        principal=Principal(id="op1", role=Role.READER),
        channel_id="cli",
    )
    for i, content in enumerate(contents):
        session.append(
            Turn(
                turn_id=f"t{i}",
                direction="inbound" if i % 2 == 0 else "outbound",
                content=content,
            )
        )
    return session


def _budget(history: int) -> ContextBudget:
    return ContextBudget(
        total_window=history + 1,
        base_reserve=0,
        output_reserve=1,
        tools_reserve=0,
        memory_reserve=0,
    )


def _fixed_tokens(_: str) -> int:
    return 10


def test_turns_become_verbatim_entries_in_order() -> None:
    session = _session("hello", "hi there", "restart vm-1")
    ctx = session_to_working_context(
        session=session, budget=_budget(1000), token_estimator=_fixed_tokens
    )
    assert set(ctx.manifest.verbatim_ids) == {"t0", "t1", "t2"}
    # Prompt order: oldest verbatim first, newest last.
    order = [e.entry_id for e in ctx.entries if e.kind is EntryKind.VERBATIM]
    assert order == ["t0", "t1", "t2"]
    # Roles mapped from direction.
    roles = {e.entry_id: e.role for e in ctx.entries}
    assert roles["t0"] is EntryRole.OPERATOR
    assert roles["t1"] is EntryRole.ASSISTANT


def test_verbatim_entries_are_untrusted() -> None:
    session = _session("hello")
    ctx = session_to_working_context(
        session=session, budget=_budget(1000), token_estimator=_fixed_tokens
    )
    assert all(not e.trusted for e in ctx.entries)


def test_typed_facts_are_included_and_trusted() -> None:
    session = _session("hello")
    fact = TranscriptEntry(
        entry_id="audit-1",
        role=EntryRole.SYSTEM,
        kind=EntryKind.TYPED_FACT,
        text="T0 verdict: deny",
        tokens=10,
        sequence=0,
        trusted=True,
    )
    ctx = session_to_working_context(
        session=session,
        budget=_budget(1000),
        typed_facts=[fact],
        token_estimator=_fixed_tokens,
    )
    assert "audit-1" in ctx.manifest.typed_fact_ids


def test_pinned_turn_survives_budget_pressure() -> None:
    session = _session(*[f"turn {i}" for i in range(10)])
    # Only room for ~2 turns; pin the oldest so it is not dropped.
    ctx = session_to_working_context(
        session=session,
        budget=_budget(20),
        pinned_ids=frozenset({"t0"}),
        token_estimator=_fixed_tokens,
    )
    assert "t0" in ctx.manifest.pinned_ids
    assert "t0" not in ctx.manifest.dropped_ids


def test_bounded_under_budget_regardless_of_length() -> None:
    session = _session(*[f"turn {i}" for i in range(500)])
    ctx = session_to_working_context(
        session=session, budget=_budget(100), token_estimator=_fixed_tokens
    )
    assert ctx.total_tokens <= 100


def test_empty_content_turns_skipped() -> None:
    session = ConversationSession(
        session_id="s1",
        principal=Principal(id="op1", role=Role.READER),
        channel_id="cli",
    )
    session.append(Turn(turn_id="t0", direction="inbound", content=""))
    session.append(Turn(turn_id="t1", direction="inbound", content="real"))
    ctx = session_to_working_context(
        session=session, budget=_budget(1000), token_estimator=_fixed_tokens
    )
    assert ctx.manifest.verbatim_ids == ("t1",)
