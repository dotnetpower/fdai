"""Read-only context-selection comparison panel tests."""

from __future__ import annotations

import pytest

from fdai.core.working_context import InMemoryContextSelectionEvaluationStore
from fdai.delivery.read_api.routes.context_selection_comparisons import (
    ContextSelectionComparisonPanel,
)
from fdai.delivery.read_api.routes.panels import PanelQueryError
from tests.core.working_context.test_evidence import evaluation


async def test_panel_projects_comparison_without_mutation_controls() -> None:
    store = InMemoryContextSelectionEvaluationStore()
    await store.append(evaluation())
    panel = ContextSelectionComparisonPanel(store)

    payload = await panel.render(params={"limit": "10"})

    assert payload["read_only"] is True
    assert payload["mutation_controls"] is False
    assert payload["count"] == 1
    assert payload["invariant_failures"] == 0
    row = payload["comparisons"][0]
    assert row["baseline_tokens"] == 10
    assert row["candidate_tokens"] == 10
    assert row["evidence_overlap"] == 1.0
    assert row["omissions"] == []
    assert row["pinned_preserved"] is True


async def test_panel_rejects_unbounded_limit() -> None:
    panel = ContextSelectionComparisonPanel(InMemoryContextSelectionEvaluationStore())

    with pytest.raises(PanelQueryError, match="limit MUST be in"):
        await panel.render(params={"limit": "201"})
