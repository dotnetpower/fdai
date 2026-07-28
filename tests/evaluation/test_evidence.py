"""Bounded evaluation evidence collection tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai_evaluation_sdk import (
    Capability,
    EvaluationTask,
    ResourceLimits,
    SideEffectClass,
    TargetRef,
)

from fdai.evaluation.evidence import BoundedEvaluationEvidenceCollector

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _task() -> EvaluationTask:
    return EvaluationTask(
        session_id="session-1",
        task_id="task-1",
        phase="diagnosis",
        objective="Diagnose a bounded Kubernetes incident.",
        target=TargetRef(kind="kubernetes.namespace", value="example"),
        requested_capabilities=(
            Capability(
                capability_id="observe.kubernetes.inventory",
                side_effect_class=SideEffectClass.OBSERVE,
            ),
            Capability(
                capability_id="observe.logs.query",
                side_effect_class=SideEffectClass.OBSERVE,
            ),
        ),
        deadline=_NOW + timedelta(minutes=5),
        resource_limits=ResourceLimits(
            cpu_seconds=60,
            memory_bytes=268_435_456,
            process_count=16,
            output_bytes=1_048_576,
            wall_clock_seconds=120,
        ),
    )


class _Provider:
    async def collect(self, task: EvaluationTask):  # type: ignore[no-untyped-def]
        return {"namespace": task.target.value, "pods": 2}


class _FailingProvider:
    async def collect(self, task: EvaluationTask):  # type: ignore[no-untyped-def]
        del task
        raise RuntimeError("provider detail must not escape")


async def test_collects_only_allowed_capabilities_and_marks_missing_provider() -> None:
    collector = BoundedEvaluationEvidenceCollector(
        providers={"observe.kubernetes.inventory": _Provider()}
    )

    evidence = await collector.collect(
        task=_task(),
        allowed_capabilities=frozenset({"observe.kubernetes.inventory", "observe.logs.query"}),
    )

    assert evidence["observe.kubernetes.inventory"] == {
        "status": "available",
        "payload": {"namespace": "example", "pods": 2},
    }
    assert evidence["observe.logs.query"] == {
        "status": "unavailable",
        "reason": "provider_unconfigured",
    }


async def test_provider_failure_and_oversize_fail_closed_without_detail() -> None:
    failing = BoundedEvaluationEvidenceCollector(
        providers={"observe.kubernetes.inventory": _FailingProvider()}
    )
    failed = await failing.collect(
        task=_task(),
        allowed_capabilities=frozenset({"observe.kubernetes.inventory"}),
    )
    assert failed["observe.kubernetes.inventory"] == {
        "status": "unavailable",
        "reason": "provider_error",
    }

    class _OversizedProvider:
        async def collect(self, task: EvaluationTask):  # type: ignore[no-untyped-def]
            del task
            return {"content": "x" * 100}

    oversized = BoundedEvaluationEvidenceCollector(
        providers={"observe.kubernetes.inventory": _OversizedProvider()},
        max_item_bytes=32,
        max_total_bytes=128,
    )
    result = await oversized.collect(
        task=_task(),
        allowed_capabilities=frozenset({"observe.kubernetes.inventory"}),
    )
    assert result["observe.kubernetes.inventory"] == {
        "status": "unavailable",
        "reason": "response_over_limit",
    }
