"""Tests for assemble_turn_context (end-to-end turn assembly)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from fdai.core.conversation.context_bridge import assemble_turn_context
from fdai.core.conversation.session import (
    ConversationSession,
    Principal,
    Role,
    Turn,
)
from fdai.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)
from fdai.core.working_context.types import ContextBudget, TranscriptEntry


class _KeywordEmbedderRetriever:
    """Fake retriever: returns candidates whose text contains the utterance."""

    async def retrieve(
        self,
        *,
        utterance: str,
        candidates: Sequence[TranscriptEntry],
        k: int,
    ) -> Sequence[TranscriptEntry]:
        hits = [c for c in candidates if utterance.lower() in c.text.lower()]
        return tuple(hits[:k])


def _session(*contents: str) -> ConversationSession:
    session = ConversationSession(
        session_id="s1",
        principal=Principal(id="op1", role=Role.READER),
        channel_id="cli",
    )
    for i, content in enumerate(contents):
        session.append(Turn(turn_id=f"t{i}", direction="inbound", content=content))
    return session


def _memory(uid: str, body: str = "always tag prod") -> OperatorMemoryEntry:
    return OperatorMemoryEntry(
        id=UUID(uid),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="rg-prod",
        category=MemoryCategory.PREFERENCE,
        body=body,
        source_event=MemorySource.CHATOPS_PREFERENCE,
        source_ref="msg-1",
        author="op-a",
        approved_by="op-b",
        created_at=datetime.now(tz=UTC),
    )


_U0 = "00000000-0000-0000-0000-000000000000"


def _budget(history: int) -> ContextBudget:
    return ContextBudget(
        total_window=history + 1,
        base_reserve=0,
        output_reserve=1,
        tools_reserve=0,
        memory_reserve=0,
    )


async def test_without_retriever_reduces_to_verbatim_plus_memory() -> None:
    session = _session("hello", "world")
    ctx = await assemble_turn_context(
        session=session,
        utterance="anything",
        budget=_budget(1000),
        operator_memory=[_memory(_U0)],
    )
    assert set(ctx.manifest.verbatim_ids) == {"t0", "t1"}
    assert f"opmem-{_U0}" in ctx.manifest.typed_fact_ids
    assert ctx.manifest.retrieved_ids == ()


async def test_retriever_pulls_back_relevant_older_turn() -> None:
    # Long session; a tight budget keeps only the newest turns verbatim, but
    # the retriever brings back the older matching turn.
    session = _session(
        "vm-1 crashed hard",
        *[f"unrelated padding {i}" for i in range(10)],
    )
    ctx = await assemble_turn_context(
        session=session,
        utterance="crashed",
        budget=_budget(30),
        retriever=_KeywordEmbedderRetriever(),
        retrieval_k=3,
    )
    # t0 (the crash turn) is oldest and outside the verbatim window, yet it
    # returns through the retrieval tier because it matches "crashed".
    assert "t0" in ctx.manifest.retrieved_ids or "t0" in ctx.manifest.verbatim_ids


async def test_dedup_when_retrieved_equals_verbatim() -> None:
    session = _session("crashed now")
    ctx = await assemble_turn_context(
        session=session,
        utterance="crashed",
        budget=_budget(1000),
        retriever=_KeywordEmbedderRetriever(),
    )
    all_ids = ctx.manifest.verbatim_ids + ctx.manifest.retrieved_ids
    assert all_ids.count("t0") == 1


async def test_empty_session_and_no_retriever() -> None:
    session = _session()
    ctx = await assemble_turn_context(session=session, utterance="hi", budget=_budget(100))
    assert ctx.entries == ()


async def test_bounded_under_budget() -> None:
    session = _session(*[f"turn {i} padding text" for i in range(200)])
    ctx = await assemble_turn_context(
        session=session,
        utterance="turn",
        budget=_budget(100),
        retriever=_KeywordEmbedderRetriever(),
    )
    assert ctx.total_tokens <= 100


async def test_forbidden_memory_pinned_end_to_end() -> None:
    session = _session(*[f"pad {i}" for i in range(20)])
    forbidden = OperatorMemoryEntry(
        id=UUID(_U0),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="rg-prod",
        category=MemoryCategory.FORBIDDEN_ACTION,
        body="never delete rg-prod",
        source_event=MemorySource.OVERRIDE_CREATE,
        source_ref="ov-1",
        author="op-a",
        approved_by="op-b",
        created_at=datetime.now(tz=UTC),
    )
    ctx = await assemble_turn_context(
        session=session,
        utterance="status",
        budget=_budget(50),
        operator_memory=[forbidden],
    )
    assert f"opmem-{_U0}" in ctx.manifest.pinned_ids
