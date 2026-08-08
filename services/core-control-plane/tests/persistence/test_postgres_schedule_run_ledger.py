"""PostgreSQL scheduler dispatch ledger persistence and transition tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.run_ledger import ScheduleDispatchRun, ScheduleDispatchStatus
from fdai.delivery.persistence.postgres_schedule_run_ledger import (
    PostgresScheduleRunLedger,
    PostgresScheduleRunLedgerConfig,
)
from fdai.delivery.persistence.postgres_scheduler_store import (
    PostgresScheduleStore,
    PostgresScheduleStoreConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 7, 17, 1, 0, tzinfo=UTC)


def test_config_rejects_empty_dsn_or_bad_timeout() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresScheduleRunLedgerConfig(dsn="")
    with pytest.raises(ValueError, match="timeouts"):
        PostgresScheduleRunLedgerConfig(dsn="postgresql://x", connect_timeout_s=0)


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _plain_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.integration
async def test_claim_retry_reconcile_and_restart_persist() -> None:
    url = _requires_live_db()
    _upgrade_head()
    dsn = _plain_dsn(url)
    task_id = f"task-{uuid.uuid4().hex[:10]}"
    run_id = f"schedule:{task_id}:1"
    tasks = PostgresScheduleStore(config=PostgresScheduleStoreConfig(dsn=dsn))
    await tasks.create(
        ScheduledTask(
            task_id=task_id,
            name="ledger test",
            interval_seconds=60,
            event_type="synthetic.ledger.test",
            created_by="operator-example",
        )
    )
    config = PostgresScheduleRunLedgerConfig(dsn=dsn)
    ledger = PostgresScheduleRunLedger(config=config)
    run = ScheduleDispatchRun(
        run_id=run_id,
        task_id=task_id,
        scheduled_for=_NOW,
        claimed_at=_NOW,
    )

    assert await ledger.claim(run) is True
    assert await ledger.claim(run) is False
    await ledger.complete(
        run_id,
        status=ScheduleDispatchStatus.FAILED,
        at=_NOW,
        error_kind="SyntheticFailure",
    )
    assert await ledger.claim(run) is True

    lost = await ledger.reconcile_stale(
        before=_NOW,
        at=_NOW + timedelta(minutes=16),
    )
    assert lost[0].status is ScheduleDispatchStatus.LOST
    assert await ledger.claim(run) is True
    published = await ledger.complete(
        run_id,
        status=ScheduleDispatchStatus.PUBLISHED,
        at=_NOW + timedelta(minutes=17),
    )
    assert published.attempt == 3

    restarted = PostgresScheduleRunLedger(config=config)
    assert await restarted.claim(run) is False
    history = await restarted.list_for_task(task_id)
    assert history[0].status is ScheduleDispatchStatus.PUBLISHED
    await tasks.cancel(task_id)
