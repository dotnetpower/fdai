"""Generic runner tests over only the public SDK protocols."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta

import pytest

from fdai_evaluation_sdk import (
    EVALUATION_API_VERSION,
    ArtifactPolicy,
    AuthorityCeiling,
    DecisionReceipt,
    EvaluationRequest,
    EvaluationResult,
    EvaluationRunError,
    EvaluationRunner,
    EvaluationStatus,
    EvaluationTask,
    QualityGateStatus,
    ResourceLimits,
    TargetRef,
    WorkspacePolicy,
)

_NOW = datetime(2026, 7, 29, tzinfo=UTC)


def _request() -> EvaluationRequest:
    return EvaluationRequest(
        session_id="session-1",
        requester_id="driver-1",
        purpose="Run a bounded evaluation.",
        requested_capabilities=(),
        authority_ceiling=AuthorityCeiling.SHADOW,
        task_count_limit=2,
        concurrency_limit=1,
        deadline=_NOW + timedelta(hours=1),
        workspace_policy=WorkspacePolicy(),
        artifact_policy=ArtifactPolicy(
            allowed_media_types=("text/plain",),
            max_artifact_bytes=1_024,
        ),
    )


def _task(task_id: str = "task-1") -> EvaluationTask:
    return EvaluationTask(
        session_id="session-1",
        task_id=task_id,
        phase="inspect",
        objective="Inspect bounded evidence.",
        target=TargetRef(kind="service", value="example"),
        deadline=_NOW + timedelta(minutes=10),
        resource_limits=ResourceLimits(
            cpu_seconds=10,
            memory_bytes=1_048_576,
            process_count=1,
            output_bytes=1_024,
            wall_clock_seconds=10,
        ),
    )


def _result(task: EvaluationTask) -> EvaluationResult:
    return EvaluationResult(
        session_id=task.session_id,
        task_id=task.task_id,
        phase=task.phase,
        status=EvaluationStatus.HELD,
        summary="Held for review.",
        terminal_audit_ref="audit/1",
        reason_code="insufficient_evidence",
        decision_receipt=DecisionReceipt(
            selected_tier="t0",
            control_loop_outcome="abstained",
            decision="abstain",
            autonomy_mode=AuthorityCeiling.SHADOW,
            verifier_passed=True,
            quality_gate_status=QualityGateStatus.NOT_REQUIRED,
            authority_ceiling=AuthorityCeiling.SHADOW,
        ),
    )


class _Adapter:
    adapter_id = "example"

    def __init__(self, tasks: tuple[EvaluationTask, ...]) -> None:
        self.tasks = deque(tasks)
        self.results: list[EvaluationResult] = []
        self.closed = False

    async def start(self) -> EvaluationRequest:
        return _request()

    async def next_task(self) -> EvaluationTask | None:
        return self.tasks.popleft() if self.tasks else None

    async def submit(self, result: EvaluationResult) -> None:
        self.results.append(result)

    async def close(self) -> None:
        self.closed = True


class _Session:
    session_id = "session-1"

    def __init__(self) -> None:
        self.closed = False

    async def execute(self, task: EvaluationTask) -> EvaluationResult:
        return _result(task)

    async def publish_artifact(self, **_: object):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def read_artifact(self, artifact):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def record_external_validation(self, receipt) -> None:  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def close(self) -> None:
        self.closed = True


class _Host:
    api_version = EVALUATION_API_VERSION

    def __init__(self, session: _Session) -> None:
        self.session = session

    async def open(self, request: EvaluationRequest) -> _Session:
        assert request.session_id == self.session.session_id
        return self.session

    async def record_external_validation(self, receipt) -> None:  # type: ignore[no-untyped-def]
        return None


async def test_runner_processes_correlated_tasks_and_cleans_both_sides() -> None:
    adapter = _Adapter((_task("task-1"), _task("task-2")))
    session = _Session()

    summary = await EvaluationRunner(adapter=adapter, host=_Host(session)).run()

    assert summary.task_count == 2
    assert summary.held_count == 2
    assert [result.task_id for result in adapter.results] == ["task-1", "task-2"]
    assert adapter.closed is True
    assert session.closed is True


async def test_runner_rejects_duplicate_before_second_execution() -> None:
    task = _task()
    adapter = _Adapter((task, task))
    session = _Session()

    with pytest.raises(EvaluationRunError, match="duplicate"):
        await EvaluationRunner(adapter=adapter, host=_Host(session)).run()

    assert len(adapter.results) == 1
    assert adapter.closed is True
    assert session.closed is True


async def test_runner_cancellation_still_closes_session_and_adapter() -> None:
    class _BlockingSession(_Session):
        async def execute(self, task: EvaluationTask) -> EvaluationResult:
            await asyncio.Event().wait()
            return _result(task)

    adapter = _Adapter((_task(),))
    session = _BlockingSession()
    execution = asyncio.create_task(EvaluationRunner(adapter=adapter, host=_Host(session)).run())
    await asyncio.sleep(0)
    execution.cancel()

    with pytest.raises(asyncio.CancelledError):
        await execution

    assert adapter.closed is True
    assert session.closed is True


def test_runner_rejects_incompatible_host_api() -> None:
    host = _Host(_Session())
    host.api_version = "2.0"

    with pytest.raises(EvaluationRunError, match="incompatible"):
        EvaluationRunner(adapter=_Adapter(()), host=host)
