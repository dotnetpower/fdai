"""Read-only scheduler dispatch history pagination tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.scheduler import (
    InMemoryScheduleRunLedger,
    ScheduleDispatchRun,
    ScheduleDispatchStatus,
    ScheduleRunHistoryService,
)

_NOW = datetime(2026, 7, 17, 6, 0, tzinfo=UTC)


async def _history() -> ScheduleRunHistoryService:
    ledger = InMemoryScheduleRunLedger()
    for index, status in enumerate(
        (
            ScheduleDispatchStatus.PUBLISHED,
            ScheduleDispatchStatus.FAILED,
            ScheduleDispatchStatus.PUBLISHED,
        )
    ):
        at = _NOW + timedelta(minutes=index)
        run = ScheduleDispatchRun(
            run_id=f"schedule:t1:{index}",
            task_id="t1",
            scheduled_for=at,
            claimed_at=at,
        )
        await ledger.claim(run)
        await ledger.complete(
            run.run_id,
            status=status,
            at=at,
            error_kind="SyntheticFailure" if status is ScheduleDispatchStatus.FAILED else None,
        )
    return ScheduleRunHistoryService(ledger=ledger)


async def test_history_is_newest_first_and_cursor_stable() -> None:
    service = await _history()

    first = await service.list(task_id="t1", limit=2)
    second = await service.list(task_id="t1", limit=2, cursor=first.next_cursor)

    assert [item.run_id for item in first.items] == ["schedule:t1:2", "schedule:t1:1"]
    assert [item.run_id for item in second.items] == ["schedule:t1:0"]
    assert second.next_cursor is None


async def test_history_filters_status_and_projects_safe_fields() -> None:
    service = await _history()

    page = await service.list(task_id="t1", status=ScheduleDispatchStatus.FAILED)

    assert len(page.items) == 1
    assert page.items[0].status == "failed"
    assert page.items[0].error_kind == "SyntheticFailure"
    assert page.items[0].completed_at is not None


async def test_invalid_cursor_or_limit_fails_closed() -> None:
    service = await _history()
    with pytest.raises(ValueError, match="cursor"):
        await service.list(task_id="t1", cursor="not-a-cursor")
    with pytest.raises(ValueError, match="limit"):
        await service.list(task_id="t1", limit=201)
