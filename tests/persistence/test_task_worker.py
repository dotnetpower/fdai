from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai.core.task_worker import (
    AttenuatedCapabilities,
    TaskWorkerBudget,
    TaskWorkerConflictError,
    TaskWorkerOutput,
    TaskWorkerRequest,
    TaskWorkerResult,
    TaskWorkerRuntime,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerUsage,
)
from fdai.delivery.persistence import (
    PostgresTaskWorkerStore,
    PostgresTaskWorkerStoreConfig,
)

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 7, 20, 8, tzinfo=UTC)


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


def _request(worker_id: str) -> TaskWorkerRequest:
    return TaskWorkerRequest(
        worker_id=worker_id,
        parent_trace_ref=f"trace-{worker_id}",
        cancellation_owner="principal-example",
        goal="Inspect bounded evidence.",
        evidence_refs=("audit:1",),
        constraints=("Read only.",),
        requested_tools=frozenset({"query_audit"}),
        budget=TaskWorkerBudget(),
        created_at=_NOW,
    )


class _UnusedExecutor:
    async def execute(self, **_kwargs: object) -> TaskWorkerOutput:
        raise AssertionError("recovery MUST NOT invoke the executor")


@pytest.mark.integration
async def test_worker_store_round_trip_cas_and_events_survive_restart() -> None:
    _upgrade()
    worker_id = f"worker-{uuid.uuid4().hex}"
    store = PostgresTaskWorkerStore(config=PostgresTaskWorkerStoreConfig(dsn=_dsn()))
    request = _request(worker_id)
    snapshot = TaskWorkerSnapshot(
        request=request,
        capabilities=AttenuatedCapabilities(frozenset({"query_audit"})),
        status=TaskWorkerStatus.PENDING,
        usage=TaskWorkerUsage(),
        updated_at=_NOW,
    )
    stored, created = await store.create(snapshot)
    assert created and stored == snapshot
    await store.append_event(worker_id, kind="worker.created", at=_NOW)
    running = await store.transition(
        worker_id,
        expected=frozenset({TaskWorkerStatus.PENDING}),
        status=TaskWorkerStatus.RUNNING,
        usage=TaskWorkerUsage(),
        at=_NOW + timedelta(seconds=1),
    )
    heartbeat = await store.heartbeat(
        worker_id,
        usage=TaskWorkerUsage(tool_calls=1),
        at=_NOW + timedelta(seconds=2),
    )
    assert heartbeat.heartbeat_at == _NOW + timedelta(seconds=2)
    result = TaskWorkerResult(
        worker_id=worker_id,
        parent_trace_ref=request.parent_trace_ref,
        status=TaskWorkerStatus.SUCCEEDED,
        summary="Completed.",
        evidence_refs=("audit:1",),
        caveats=(),
        usage=TaskWorkerUsage(tokens=10, tool_calls=1),
        terminal_reason="completed",
        started_at=running.updated_at,
        finished_at=_NOW + timedelta(seconds=3),
    )
    await store.transition(
        worker_id,
        expected=frozenset({TaskWorkerStatus.RUNNING}),
        status=result.status,
        usage=result.usage,
        at=result.finished_at,
        result=result,
    )
    await store.append_event(worker_id, kind="worker.succeeded", at=result.finished_at)
    with pytest.raises(TaskWorkerConflictError):
        await store.transition(
            worker_id,
            expected=frozenset({TaskWorkerStatus.RUNNING}),
            status=TaskWorkerStatus.FAILED,
            usage=result.usage,
            at=result.finished_at,
            result=result,
        )

    restarted = PostgresTaskWorkerStore(config=PostgresTaskWorkerStoreConfig(dsn=_dsn()))
    loaded = await restarted.get(worker_id)
    owner_loaded = await restarted.get(worker_id, owner=request.cancellation_owner)
    hidden = await restarted.get(worker_id, owner="another-principal")
    owner_list = await restarted.list(owner=request.cancellation_owner)
    hidden_list = await restarted.list(owner="another-principal")

    assert loaded is not None and loaded.result == result
    assert owner_loaded == loaded
    assert hidden is None
    assert worker_id in {item.request.worker_id for item in owner_list}
    assert worker_id not in {item.request.worker_id for item in hidden_list}
    assert [event.sequence for event in await restarted.events(worker_id)] == [0, 1]
    assert [
        event.sequence
        for event in await restarted.events(worker_id, owner=request.cancellation_owner)
    ] == [0, 1]
    with pytest.raises(LookupError):
        await restarted.events(worker_id, owner="another-principal")


@pytest.mark.integration
async def test_runtime_recovery_terminalizes_durable_interrupted_worker() -> None:
    _upgrade()
    worker_id = f"worker-recovery-{uuid.uuid4().hex}"
    store = PostgresTaskWorkerStore(config=PostgresTaskWorkerStoreConfig(dsn=_dsn()))
    request = _request(worker_id)
    await store.create(
        TaskWorkerSnapshot(
            request=request,
            capabilities=AttenuatedCapabilities(frozenset({"query_audit"})),
            status=TaskWorkerStatus.RUNNING,
            usage=TaskWorkerUsage(tokens=20),
            updated_at=_NOW,
            heartbeat_at=_NOW,
        )
    )
    runtime = TaskWorkerRuntime(store=store, executor=_UnusedExecutor(), tools=())

    recovered = await runtime.recover_interrupted()

    assert any(result.worker_id == worker_id for result in recovered)
    loaded = await store.get(worker_id)
    assert loaded is not None
    assert loaded.status is TaskWorkerStatus.FAILED
    assert loaded.result is not None
    assert loaded.result.terminal_reason == "runtime_restart_interrupted"
