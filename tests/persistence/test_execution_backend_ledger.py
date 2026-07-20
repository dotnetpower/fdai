"""PostgreSQL execution submission ledger survives restart with CAS state."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.delivery.persistence import (
    PostgresExecutionSubmissionLedger,
    PostgresExecutionSubmissionLedgerConfig,
)
from fdai.shared.providers.execution_backend import (
    ExecutionAttempt,
    ExecutionAttemptOperation,
    ExecutionCleanupState,
    ExecutionLedgerRecord,
    ExecutionOwnerTrace,
    ExecutionStatus,
)

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 21, 13, tzinfo=UTC)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _record(key: str) -> ExecutionLedgerRecord:
    return ExecutionLedgerRecord(
        idempotency_key=key,
        workload_id="report.render",
        artifact_digest="a" * 64,
        profile_id="aca.report",
        profile_version="1.0.0",
        backend_kind="azure_container_apps_job",
        owner_trace=ExecutionOwnerTrace(
            event_ref="event:1",
            action_ref="action:1",
            correlation_ref="trace:1",
        ),
        stop_condition="stop after timeout",
        audit_ref="audit:action:1",
        scope_ref="resource:job:example",
        region="example-region",
        status=ExecutionStatus.PLANNED,
        submission_ref=None,
        receipt_ref=None,
        detail="planned",
        cancel_requested=False,
        cleanup_state=ExecutionCleanupState.PENDING,
        created_at=_NOW,
        updated_at=_NOW,
        retention_until=_NOW + timedelta(days=30),
    )


def test_postgres_execution_ledger_config_rejects_empty_dsn() -> None:
    with pytest.raises(ValueError, match="dsn"):
        PostgresExecutionSubmissionLedgerConfig(dsn="")


@pytest.mark.integration
async def test_submission_attempt_and_cas_state_survive_restart() -> None:
    _upgrade()
    key = f"execution-{uuid.uuid4().hex}"
    config = PostgresExecutionSubmissionLedgerConfig(dsn=_dsn())
    store = PostgresExecutionSubmissionLedger(config=config)
    created = await store.create(_record(key))
    submitted = await store.update(
        replace(
            created,
            status=ExecutionStatus.SUBMITTED,
            submission_ref="provider:run-1",
            receipt_ref="provider:run-1",
            detail="accepted",
            updated_at=_NOW + timedelta(seconds=1),
        ),
        expected_revision=0,
    )
    await store.append_attempt(
        ExecutionAttempt(
            idempotency_key=key,
            sequence=1,
            operation=ExecutionAttemptOperation.SUBMIT,
            status=ExecutionStatus.PLANNED,
            detail="planned",
            recorded_at=_NOW,
        )
    )

    restarted = PostgresExecutionSubmissionLedger(config=config)
    loaded = await restarted.get(key)
    attempts = await restarted.attempts(key)
    duplicate = await restarted.create(_record(key))

    assert loaded == submitted
    assert duplicate == submitted
    assert submitted.revision == 1
    assert [item.operation for item in attempts] == [ExecutionAttemptOperation.SUBMIT]
    with pytest.raises(RuntimeError, match="revision conflict"):
        await restarted.update(submitted, expected_revision=0)
