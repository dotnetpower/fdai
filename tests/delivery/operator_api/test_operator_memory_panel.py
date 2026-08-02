"""Operator-memory governance panel tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.operator_memory import (
    InMemoryOperatorMemoryStore,
    MemoryCategory,
    MemorySource,
    OperatorMemoryEntry,
    OperatorMemoryReviewService,
    ScopeKind,
)
from fdai.delivery.operator_api.routes.operator_memory import OperatorMemoryPanel
from fdai.delivery.operator_api.routes.panels import PanelQueryError


async def _panel() -> OperatorMemoryPanel:
    store = InMemoryOperatorMemoryStore()
    await store.append(
        OperatorMemoryEntry(
            id=UUID(int=1),
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="resource:example",
            category=MemoryCategory.RUNBOOK_HINT,
            body="Use the approved recovery runbook.",
            source_event=MemorySource.PR_REVIEW,
            source_ref="pr:123",
            author="operator-a",
            approved_by="operator-b",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
        )
    )
    return OperatorMemoryPanel(service=OperatorMemoryReviewService(store=store))


async def test_panel_projects_reviewable_governance_fields() -> None:
    payload = await (await _panel()).render(
        params={"scope_kind": "resource", "scope_ref": "resource:example"}
    )

    items = payload["items"]
    assert isinstance(items, list)
    item = items[0]
    assert item["source_ref"] == "pr:123"
    assert item["approval_state"] == "approved"
    assert item["scope_kind"] == "resource"
    assert item["active"] is True


async def test_panel_rejects_invalid_scope_or_limit() -> None:
    panel = await _panel()
    with pytest.raises(PanelQueryError, match="scope_kind"):
        await panel.render(params={"scope_kind": "organization"})
    with pytest.raises(PanelQueryError, match="limit"):
        await panel.render(params={"limit": "1000"})
