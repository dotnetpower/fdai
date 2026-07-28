"""Evaluation output custody verification tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fdai_evaluation_sdk import (
    ArtifactPolicy,
    ArtifactRef,
    ArtifactSpec,
    EvaluationTask,
    ResourceLimits,
    TargetRef,
)

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.evaluation.artifacts import (
    ArtifactCustodyError,
    InMemoryArtifactBroker,
    InMemoryArtifactCustodySink,
)
from fdai.evaluation.outputs import EvaluationOutputError, collect_verified_outputs

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _task() -> EvaluationTask:
    return EvaluationTask(
        session_id="session-1",
        task_id="task-1",
        phase="patch",
        objective="Produce a bounded patch.",
        target=TargetRef(kind="source.workspace", value="workspace-1"),
        expected_outputs=(
            ArtifactSpec(
                name="fix.patch",
                media_type="text/x-diff",
                max_bytes=1_024,
                ttl_seconds=60,
            ),
        ),
        deadline=_NOW + timedelta(minutes=1),
        resource_limits=ResourceLimits(
            cpu_seconds=1,
            memory_bytes=1_048_576,
            process_count=1,
            output_bytes=1_024,
            wall_clock_seconds=1,
        ),
    )


class _Collector:
    def __init__(self, outputs: tuple[ArtifactRef, ...]) -> None:
        self.outputs = outputs

    async def collect(self, **_: object) -> tuple[ArtifactRef, ...]:
        return self.outputs


async def _stored_output(broker: InMemoryArtifactBroker) -> ArtifactRef:
    spec = _task().expected_outputs[0]

    async def chunks() -> AsyncIterator[bytes]:
        yield b"patch"

    return await broker.publish(
        session_id="session-1",
        task_id="task-1",
        spec=spec,
        declared_outputs=(spec,),
        chunks=chunks(),
        policy=ArtifactPolicy(
            allowed_media_types=("text/x-diff",),
            max_artifact_bytes=1_024,
            max_ttl_seconds=60,
        ),
        ttl_seconds=60,
    )


def _result() -> ControlLoopResult:
    return ControlLoopResult(
        outcome=ControlLoopOutcome.EXECUTED,
        tier="t0",
        decision="patch",
        resource_type="source.workspace",
    )


async def test_requires_every_declared_output_for_completed_result() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)

    with pytest.raises(EvaluationOutputError, match="do not match"):
        await collect_verified_outputs(
            task=_task(),
            control_result=_result(),
            collector=_Collector(()),
            artifact_broker=broker,
            clock=lambda: _NOW,
            require_all=True,
        )


async def test_rejects_duplicate_and_cross_session_outputs() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)
    reference = await _stored_output(broker)
    with pytest.raises(EvaluationOutputError, match="unique"):
        await collect_verified_outputs(
            task=_task(),
            control_result=_result(),
            collector=_Collector((reference, reference)),
            artifact_broker=broker,
            clock=lambda: _NOW,
            require_all=True,
        )
    with pytest.raises(EvaluationOutputError, match="declared custody"):
        await collect_verified_outputs(
            task=_task(),
            control_result=_result(),
            collector=_Collector((reference.model_copy(update={"session_id": "session-2"}),)),
            artifact_broker=broker,
            clock=lambda: _NOW,
            require_all=True,
        )


async def test_rejects_reference_size_that_differs_from_stored_content() -> None:
    broker = InMemoryArtifactBroker(custody_sink=InMemoryArtifactCustodySink(), clock=lambda: _NOW)
    reference = await _stored_output(broker)

    with pytest.raises(ArtifactCustodyError, match="unknown or altered"):
        await collect_verified_outputs(
            task=_task(),
            control_result=_result(),
            collector=_Collector((reference.model_copy(update={"size_bytes": 6}),)),
            artifact_broker=broker,
            clock=lambda: _NOW,
            require_all=True,
        )
