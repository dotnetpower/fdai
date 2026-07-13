"""Integration test for transactional Process snapshot and event persistence."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.delivery.persistence import (
    PostgresProcessRuntimeStore,
    PostgresProcessRuntimeStoreConfig,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
    ProcessStatus,
)

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[2]


def _requires_live_db() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_postgres_process_create_transition_and_replay() -> None:
    _upgrade_head()
    store = PostgresProcessRuntimeStore(
        config=PostgresProcessRuntimeStoreConfig(dsn=_requires_live_db())
    )
    suffix = uuid.uuid4().hex
    process_id = f"process-{suffix}"
    now = datetime.now(tz=UTC)
    created_event = ProcessEvent(
        event_id=f"event-create-{suffix}",
        process_id=process_id,
        kind=ProcessEventKind.PROCESS_CREATED,
        idempotency_key=f"create-{suffix}",
        recorded_at=now,
        correlation_id=f"corr-{suffix}",
    )
    snapshot = ProcessSnapshot(
        process_id=process_id,
        workflow_ref="architecture-review",
        workflow_version="1.0.0",
        status=ProcessStatus.PENDING,
        current_step="",
        target_resource_id="scope-example",
        started_at=now,
        updated_at=now,
        correlation_id=f"corr-{suffix}",
    )
    created, is_new = await store.create(snapshot=snapshot, event=created_event)
    replayed, is_replay_new = await store.create(snapshot=snapshot, event=created_event)
    started_event = ProcessEvent(
        event_id=f"event-start-{suffix}",
        process_id=process_id,
        kind=ProcessEventKind.STEP_STARTED,
        idempotency_key=f"start-{suffix}",
        recorded_at=now + timedelta(seconds=1),
        correlation_id=f"corr-{suffix}",
        step_id="collect-evidence",
    )
    running = await store.transition(
        process_id=process_id,
        expected_revision=created.revision,
        status=ProcessStatus.RUNNING,
        current_step="collect-evidence",
        event=started_event,
    )
    jobs = await store.claim_projections(now=now + timedelta(seconds=2))

    assert is_new is True
    assert is_replay_new is False
    assert replayed == created
    assert running.revision == 2
    assert [event.kind for event in await store.events(process_id)] == [
        ProcessEventKind.PROCESS_CREATED,
        ProcessEventKind.STEP_STARTED,
    ]
    assert {job.event.event_id for job in jobs} >= {
        created_event.event_id,
        started_event.event_id,
    }
    for job in jobs:
        if job.event.process_id == process_id:
            await store.complete_projection(job.event.event_id)
