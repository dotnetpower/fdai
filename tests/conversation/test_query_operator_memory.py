"""Wave W1.6 - query_operator_memory read-only console tool."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aiopspilot.core.conversation import QueryOperatorMemoryTool
from aiopspilot.core.conversation.session import Principal, Role
from aiopspilot.core.operator_memory.store import InMemoryOperatorMemoryStore
from aiopspilot.core.operator_memory.types import (
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    ScopeKind,
)


def _principal(role: Role = Role.READER) -> Principal:
    return Principal(id="user-1", role=role)


def _entry(
    *,
    scope_kind: ScopeKind = ScopeKind.RESOURCE_GROUP,
    scope_ref: str = "rg/example",
    body: str = "avoid restart during business hours",
    author: str = "user-a",
    approved_by: str = "user-b",
    entry_id: UUID | None = None,
) -> OperatorMemoryEntry:
    return OperatorMemoryEntry(
        id=entry_id or uuid4(),
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        category=MemoryCategory.OVERRIDE_NOTE,
        body=body,
        source_event=MemorySource.HIL_REJECT,
        source_ref="hil:idem-1",
        author=author,
        approved_by=approved_by,
        created_at=datetime.now(tz=UTC),
    )


def _store_with(*entries: OperatorMemoryEntry) -> InMemoryOperatorMemoryStore:
    """Return a store pre-populated with ``entries`` (sync helper).

    The tool itself calls ``asyncio.run`` internally; tests stay sync
    (as with other system-tool tests) and use this helper to seed.
    """

    store = InMemoryOperatorMemoryStore()

    async def _fill() -> None:
        for e in entries:
            await store.append(e)

    asyncio.run(_fill())
    return store


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_tool_metadata_is_read_only() -> None:
    assert QueryOperatorMemoryTool.name == "query_operator_memory"
    assert QueryOperatorMemoryTool.rbac_floor is Role.READER
    assert QueryOperatorMemoryTool.side_effect_class == "read"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_returns_active_entries_for_scope() -> None:
    store = _store_with(
        _entry(scope_ref="rg/example"),
        _entry(scope_ref="rg/example"),
        # Different scope - should NOT appear in the result.
        _entry(scope_ref="rg/other"),
    )

    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "rg/example"},
        principal=_principal(),
    )
    assert result.status == "ok"
    data = result.data or {}
    assert data["scope_kind"] == "resource-group"
    assert data["scope_ref"] == "rg/example"
    assert data["total_active"] == 2
    assert len(data["entries"]) == 2
    for e in data["entries"]:
        assert set(e.keys()) >= {
            "id",
            "scope_kind",
            "scope_ref",
            "category",
            "body",
            "source_event",
            "source_ref",
            "author",
            "approved_by",
            "created_at",
            "ttl_seconds",
        }


def test_scope_with_no_entries_returns_abstain() -> None:
    store = _store_with()
    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource", "scope_ref": "rg/example/vm-a"},
        principal=_principal(),
    )
    assert result.status == "abstain"
    assert (result.data or {})["entries"] == []


def test_resource_scope_key_is_honoured() -> None:
    store = _store_with(
        _entry(scope_kind=ScopeKind.RESOURCE, scope_ref="rg/example/vm-a"),
    )
    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource", "scope_ref": "rg/example/vm-a"},
        principal=_principal(),
    )
    assert result.status == "ok"


def test_limit_clamps_the_projected_list() -> None:
    store = _store_with(*(_entry(scope_ref="rg/example") for _ in range(5)))

    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "rg/example", "limit": 2},
        principal=_principal(),
    )
    assert result.status == "ok"
    data = result.data or {}
    assert data["total_active"] == 5
    assert len(data["entries"]) == 2


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_missing_scope_kind_errors() -> None:
    store = _store_with()
    tool = QueryOperatorMemoryTool(store=store)
    # _require_str raises TypeError when the key is missing (value is None).
    with pytest.raises((ValueError, TypeError)):
        tool.call(
            arguments={"scope_ref": "rg/example"},
            principal=_principal(),
        )


def test_empty_scope_kind_returns_error_result() -> None:
    store = _store_with()
    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "   ", "scope_ref": "rg/example"},
        principal=_principal(),
    )
    assert result.status == "error"
    assert "scope_kind" in (result.preview or "")


def test_empty_scope_ref_returns_error_result() -> None:
    store = _store_with()
    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "   "},
        principal=_principal(),
    )
    assert result.status == "error"
    assert "scope_ref" in (result.preview or "")


def test_unknown_scope_kind_returns_error_result() -> None:
    store = _store_with()
    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "subscription", "scope_ref": "sub-1"},
        principal=_principal(),
    )
    assert result.status == "error"
    assert "scope_kind" in (result.preview or "")
    assert "resource" in (result.preview or "")
    assert "resource-group" in (result.preview or "")


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


def test_calling_does_not_mutate_the_store() -> None:
    seed = _entry(scope_ref="rg/example")
    store = _store_with(seed)
    tool = QueryOperatorMemoryTool(store=store)

    tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "rg/example"},
        principal=_principal(),
    )
    tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "rg/example"},
        principal=_principal(),
    )
    after = asyncio.run(
        store.list_active_for_scope(scope_kind=ScopeKind.RESOURCE_GROUP, scope_ref="rg/example")
    )
    assert len(after) == 1
    assert after[0].id == seed.id


def test_superseded_entries_not_returned() -> None:
    original = _entry(scope_ref="rg/example", body="old note")
    replacement = _entry(scope_ref="rg/example", body="new note")
    store = _store_with(original, replacement)

    async def _supersede() -> None:
        await store.supersede(entry_id=original.id, superseded_by=replacement.id)

    asyncio.run(_supersede())

    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "rg/example"},
        principal=_principal(),
    )
    assert result.status == "ok"
    ids = {e["id"] for e in (result.data or {})["entries"]}
    assert str(replacement.id) in ids
    assert str(original.id) not in ids


def test_evidence_refs_carry_entry_ids() -> None:
    seed = _entry(scope_ref="rg/example")
    store = _store_with(seed)
    tool = QueryOperatorMemoryTool(store=store)
    result = tool.call(
        arguments={"scope_kind": "resource-group", "scope_ref": "rg/example"},
        principal=_principal(),
    )
    assert result.evidence_refs == (f"operator-memory:{seed.id}",)
