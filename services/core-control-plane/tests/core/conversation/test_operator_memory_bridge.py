"""Tests for operator_memory_to_entries in the context bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fdai.core.conversation.context_bridge import (
    operator_memory_to_entries,
    session_to_working_context,
)
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
from fdai.core.working_context.types import ContextBudget, EntryKind


def _memory(
    uid: str,
    *,
    category: MemoryCategory = MemoryCategory.PREFERENCE,
    body: str = "always use tag X",
    scope_ref: str = "rg-prod",
) -> OperatorMemoryEntry:
    return OperatorMemoryEntry(
        id=UUID(uid),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref=scope_ref,
        category=category,
        body=body,
        source_event=MemorySource.CHATOPS_PREFERENCE,
        source_ref="msg-1",
        author="op-a",
        approved_by="op-b",
        created_at=datetime.now(tz=UTC),
    )


_U0 = "00000000-0000-0000-0000-000000000000"
_U1 = "00000000-0000-0000-0000-000000000001"


def test_memory_projects_to_trusted_typed_facts() -> None:
    entries = operator_memory_to_entries([_memory(_U0)])
    assert len(entries) == 1
    e = entries[0]
    assert e.kind is EntryKind.TYPED_FACT
    assert e.trusted is True
    assert e.entry_id == f"opmem-{_U0}"
    assert "preference@resource-group:rg-prod" in e.text
    assert "always use tag X" in e.text
    assert e.pinned is False


def test_forbidden_action_is_pinned() -> None:
    entries = operator_memory_to_entries(
        [_memory(_U0, category=MemoryCategory.FORBIDDEN_ACTION, body="never auto-restart")]
    )
    assert entries[0].pinned is True


def test_sequences_are_negative_background_and_decreasing() -> None:
    entries = operator_memory_to_entries([_memory(_U0), _memory(_U1)])
    assert entries[0].sequence == -1
    assert entries[1].sequence == -2


def test_empty_memory_returns_nothing() -> None:
    assert operator_memory_to_entries([]) == ()


def test_memory_flows_into_working_context_as_typed_fact() -> None:
    session = ConversationSession(
        session_id="s1",
        principal=Principal(id="op1", role=Role.READER),
        channel_id="cli",
    )
    session.append(Turn(turn_id="t0", direction="inbound", content="what tag?"))
    memory = operator_memory_to_entries([_memory(_U0)])
    ctx = session_to_working_context(
        session=session,
        budget=ContextBudget(
            total_window=1000,
            base_reserve=0,
            output_reserve=1,
            tools_reserve=0,
            memory_reserve=0,
        ),
        typed_facts=memory,
    )
    assert f"opmem-{_U0}" in ctx.manifest.typed_fact_ids
    # The forbidden/preference note is trusted; the operator turn is not.
    by_id = {e.entry_id: e for e in ctx.entries}
    assert by_id[f"opmem-{_U0}"].trusted is True
    assert by_id["t0"].trusted is False


def test_pinned_forbidden_survives_budget_pressure() -> None:
    session = ConversationSession(
        session_id="s1",
        principal=Principal(id="op1", role=Role.READER),
        channel_id="cli",
    )
    for i in range(20):
        session.append(Turn(turn_id=f"t{i}", direction="inbound", content=f"turn {i} padding"))
    memory = operator_memory_to_entries(
        [_memory(_U0, category=MemoryCategory.FORBIDDEN_ACTION, body="never delete rg-prod")]
    )
    ctx = session_to_working_context(
        session=session,
        budget=ContextBudget(
            total_window=60,
            base_reserve=0,
            output_reserve=1,
            tools_reserve=0,
            memory_reserve=0,
        ),
        typed_facts=memory,
    )
    assert f"opmem-{_U0}" in ctx.manifest.pinned_ids
    assert f"opmem-{_U0}" not in ctx.manifest.dropped_ids
