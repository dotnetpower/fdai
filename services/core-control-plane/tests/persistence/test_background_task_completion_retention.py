"""PostgreSQL retention checks for undeliverable background completions."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.background_task import BackgroundTaskCompletionState

from .test_background_task import (
    _NOW,
    _complete_succeeded,
    _store,
    _task,
    database_url,
)

__all__ = ["database_url"]


@pytest.mark.integration
async def test_pending_completion_is_abandoned_and_purged_at_retention(
    database_url: str,
) -> None:
    store = _store(database_url)
    task = replace(
        _task("background-pending-retention"),
        created_at=_NOW - timedelta(days=2),
        retention_until=_NOW - timedelta(days=1),
    )
    await _complete_succeeded(
        store,
        task,
        lease_token="lease:pending-retention",
        now=_NOW - timedelta(days=2),
    )

    reconciled = await store.reconcile_completion_expired(now=_NOW)
    purged = await store.purge_retained(now=_NOW)

    assert len(reconciled) == 1
    assert reconciled[0].state is BackgroundTaskCompletionState.ABANDONED
    assert reconciled[0].attempt_count == 1
    assert reconciled[0].last_error_code == "retention_expired"
    assert task.task_id in purged
    assert await store.get(task.task_id) is None
