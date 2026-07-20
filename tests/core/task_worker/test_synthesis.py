from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.conversation.answer_planning import (
    AnswerPlanningConfig,
    AnswerPlanningResult,
    PlanningStatus,
)
from fdai.core.task_worker import (
    TaskWorkerResult,
    TaskWorkerStatus,
    TaskWorkerUsage,
    synthesize_task_worker_results,
)


def _planning() -> AnswerPlanningResult:
    return AnswerPlanningResult(
        status=PlanningStatus.COMPLETED,
        primary_agent="Forseti",
        consulted_agents=("Heimdall",),
        contributions=(),
        failures=(),
        elapsed_ms=10,
        unique_evidence_count=0,
        duplicate_evidence_count=0,
        conflicting_evidence_refs=(),
        covered_sections=(),
        estimated_added_tokens=0,
        budget=AnswerPlanningConfig(),
    )


def _result(
    worker_id: str,
    *,
    status: TaskWorkerStatus = TaskWorkerStatus.SUCCEEDED,
    summary: str | None = "bounded result",
    evidence_refs: tuple[str, ...] = ("evidence:one",),
) -> TaskWorkerResult:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    return TaskWorkerResult(
        worker_id=worker_id,
        parent_trace_ref="trace:parent",
        status=status,
        summary=summary,
        evidence_refs=evidence_refs,
        caveats=("read-only investigation",),
        usage=TaskWorkerUsage(tokens=10, cost_microusd=20, tool_calls=1),
        terminal_reason="completed" if status is TaskWorkerStatus.SUCCEEDED else status.value,
        started_at=now,
        finished_at=now,
    )


def test_synthesis_preserves_answer_planning_and_marks_workers_untrusted() -> None:
    planning = _planning()

    synthesis = synthesize_task_worker_results(
        answer_planning=planning,
        results=(
            _result("worker-b", evidence_refs=("evidence:two", "evidence:one")),
            _result("worker-a"),
        ),
    )

    assert synthesis.answer_planning is planning
    assert tuple(worker.worker_id for worker in synthesis.workers) == ("worker-a", "worker-b")
    assert all(not worker.trusted for worker in synthesis.workers)
    assert synthesis.unique_evidence_refs == ("evidence:one", "evidence:two")
    assert synthesis.total_usage == TaskWorkerUsage(tokens=20, cost_microusd=40, tool_calls=2)
    assert synthesis.to_dict()["trusted"] is False


def test_synthesis_drops_summary_from_failed_worker() -> None:
    synthesis = synthesize_task_worker_results(
        answer_planning=_planning(),
        results=(
            _result(
                "worker-failed",
                status=TaskWorkerStatus.FAILED,
                summary="must not enter parent context",
                evidence_refs=(),
            ),
        ),
    )

    assert synthesis.workers[0].summary is None
    assert synthesis.workers[0].terminal_reason == TaskWorkerStatus.FAILED.value


def test_synthesis_rejects_duplicate_or_unbounded_worker_sets() -> None:
    duplicate = _result("worker-duplicate")
    with pytest.raises(ValueError, match="unique worker ids"):
        synthesize_task_worker_results(
            answer_planning=_planning(),
            results=(duplicate, duplicate),
        )
    with pytest.raises(ValueError, match="at most 8"):
        synthesize_task_worker_results(
            answer_planning=_planning(),
            results=tuple(_result(f"worker-{index}") for index in range(9)),
        )
