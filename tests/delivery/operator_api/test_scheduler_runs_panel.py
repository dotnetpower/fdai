"""Tests for the read-only scheduler dispatch history panel."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.scheduler import (
    InMemoryScheduleRunLedger,
    ScheduleDispatchRun,
    ScheduleDispatchStatus,
    ScheduleRunHistoryService,
)
from fdai.delivery.operator_api.routes.panels import PanelQueryError
from fdai.delivery.operator_api.routes.scheduler_runs import SchedulerRunsPanel


async def _panel() -> SchedulerRunsPanel:
    ledger = InMemoryScheduleRunLedger()
    now = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    run = ScheduleDispatchRun(
        run_id="schedule:inventory:20260717T080000Z",
        task_id="inventory",
        scheduled_for=now,
        claimed_at=now,
    )
    await ledger.claim(run)
    await ledger.complete(run.run_id, status=ScheduleDispatchStatus.PUBLISHED, at=now)
    return SchedulerRunsPanel(
        service=ScheduleRunHistoryService(ledger=ledger),
        source="in-memory-test",
        durable=False,
    )


async def test_panel_projects_task_scoped_history() -> None:
    payload = await (await _panel()).render(params={"task_id": "inventory"})

    assert payload["task_id"] == "inventory"
    assert payload["source"] == "in-memory-test"
    assert payload["durable"] is False
    items = payload["items"]
    assert isinstance(items, list)
    assert items[0]["status"] == "published"
    assert items[0]["attempt"] == 1


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "task_id"),
        ({"task_id": "inventory", "limit": "many"}, "limit"),
        ({"task_id": "inventory", "status": "unknown"}, "unknown"),
    ],
)
async def test_panel_rejects_invalid_queries(
    params: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(PanelQueryError, match=message):
        await (await _panel()).render(params=params)
