"""Operator memory review projection tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from fdai.core.operator_memory import (
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    OperatorMemoryReviewService,
    ScopeKind,
)

_NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)


def _entry(uid: int, *, ttl_seconds: int | None = None) -> OperatorMemoryEntry:
    return OperatorMemoryEntry(
        id=UUID(int=uid),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="resource-group:example",
        category=MemoryCategory.PREFERENCE,
        body=f"review body {uid}",
        source_event=MemorySource.HIL_REJECT,
        source_ref=f"hil.reject:{uid}",
        author="operator-a",
        approved_by="operator-b",
        created_at=_NOW,
        ttl_seconds=ttl_seconds,
    )


async def test_review_includes_provenance_approval_expiry_and_supersession() -> None:
    store = InMemoryOperatorMemoryStore()
    expired = _entry(1, ttl_seconds=60)
    replacement = replace(_entry(2), created_at=_NOW)
    await store.append(expired)
    await store.append(replacement)
    await store.supersede(entry_id=expired.id, superseded_by=replacement.id)
    service = OperatorMemoryReviewService(
        store=store,
        clock=lambda: datetime(2026, 7, 17, 10, 2, tzinfo=UTC),
    )

    items = await service.list(scope_ref="resource-group:example")

    by_id = {item.id: item for item in items}
    old = by_id[str(expired.id)]
    assert old.source_ref == "hil.reject:1"
    assert old.approval_state == "approved"
    assert old.approved_by == "operator-b"
    assert old.expired is True
    assert old.superseded_by == str(replacement.id)
    assert old.active is False
    assert by_id[str(replacement.id)].active is True
