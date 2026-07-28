"""FDAI-owned collection and custody verification for evaluation outputs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai_evaluation_sdk import ArtifactRef, EvaluationTask

from fdai.core.control_loop import ControlLoopResult
from fdai.evaluation.artifacts import InMemoryArtifactBroker


class EvaluationOutputError(RuntimeError):
    """Collected outputs do not match the task declaration or artifact custody."""


@runtime_checkable
class EvaluationOutputCollector(Protocol):
    """Resolve task output references without interpreting benchmark grading."""

    async def collect(
        self,
        *,
        task: EvaluationTask,
        control_result: ControlLoopResult,
    ) -> tuple[ArtifactRef, ...]: ...


class NoopEvaluationOutputCollector:
    async def collect(
        self,
        *,
        task: EvaluationTask,
        control_result: ControlLoopResult,
    ) -> tuple[ArtifactRef, ...]:
        return ()


async def collect_verified_outputs(
    *,
    task: EvaluationTask,
    control_result: ControlLoopResult,
    collector: EvaluationOutputCollector,
    artifact_broker: InMemoryArtifactBroker,
    clock: Callable[[], datetime],
    require_all: bool,
) -> tuple[ArtifactRef, ...]:
    """Verify collector refs against declarations, scope, expiry, bytes, and digest."""

    outputs = tuple(await collector.collect(task=task, control_result=control_result))
    expected = {spec.name: spec for spec in task.expected_outputs}
    actual = {artifact.name: artifact for artifact in outputs}
    if len(actual) != len(outputs):
        raise EvaluationOutputError("evaluation output names MUST be unique")
    if not actual.keys() <= expected.keys() or (require_all and actual.keys() != expected.keys()):
        raise EvaluationOutputError("evaluation outputs do not match the task declaration")
    now = clock()
    for name, artifact in actual.items():
        spec = expected[name]
        if (
            artifact.session_id != task.session_id
            or artifact.task_id != task.task_id
            or artifact.media_type != spec.media_type
            or artifact.executable != spec.executable
            or artifact.size_bytes > spec.max_bytes
            or artifact.expires_at <= now
        ):
            raise EvaluationOutputError("evaluation output violates its declared custody")
        content_size = 0
        async for chunk in artifact_broker.read(
            session_id=task.session_id,
            artifact=artifact,
        ):
            content_size += len(chunk)
        if content_size != artifact.size_bytes:
            raise EvaluationOutputError("evaluation output size does not match stored content")
    return outputs


__all__ = [
    "EvaluationOutputCollector",
    "EvaluationOutputError",
    "NoopEvaluationOutputCollector",
    "collect_verified_outputs",
]
