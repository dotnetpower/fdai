"""Bounded parent synthesis for isolated task-worker results."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.conversation.answer_planning import AnswerPlanningResult
from fdai.core.task_worker.models import TaskWorkerResult, TaskWorkerStatus, TaskWorkerUsage

_MAX_WORKERS = 8
_MAX_SUMMARY_CHARS = 4_000


@dataclass(frozen=True, slots=True)
class TaskWorkerContribution:
    """One untrusted worker result projected into the parent context."""

    worker_id: str
    status: TaskWorkerStatus
    summary: str | None
    evidence_refs: tuple[str, ...]
    caveats: tuple[str, ...]
    usage: TaskWorkerUsage
    terminal_reason: str
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.trusted:
            raise ValueError("task worker contributions MUST remain untrusted")
        if self.summary is not None and len(self.summary) > _MAX_SUMMARY_CHARS:
            raise ValueError("task worker contribution summary exceeds cap")


@dataclass(frozen=True, slots=True)
class TaskWorkerSynthesis:
    """Shadow planning metadata plus bounded worker contributions."""

    answer_planning: AnswerPlanningResult
    workers: tuple[TaskWorkerContribution, ...]
    total_usage: TaskWorkerUsage
    unique_evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": "shadow",
            "trusted": False,
            "answer_planning": self.answer_planning.to_dict(),
            "workers": [
                {
                    "worker_id": worker.worker_id,
                    "status": worker.status.value,
                    "summary": worker.summary,
                    "evidence_refs": list(worker.evidence_refs),
                    "caveats": list(worker.caveats),
                    "usage": {
                        "tokens": worker.usage.tokens,
                        "cost_microusd": worker.usage.cost_microusd,
                        "tool_calls": worker.usage.tool_calls,
                    },
                    "terminal_reason": worker.terminal_reason,
                    "trusted": False,
                }
                for worker in self.workers
            ],
            "total_usage": {
                "tokens": self.total_usage.tokens,
                "cost_microusd": self.total_usage.cost_microusd,
                "tool_calls": self.total_usage.tool_calls,
            },
            "unique_evidence_refs": list(self.unique_evidence_refs),
        }


def synthesize_task_worker_results(
    *,
    answer_planning: AnswerPlanningResult,
    results: tuple[TaskWorkerResult, ...],
) -> TaskWorkerSynthesis:
    """Project bounded terminal results without changing #28 routing output."""

    if len(results) > _MAX_WORKERS:
        raise ValueError(f"task worker synthesis accepts at most {_MAX_WORKERS} results")
    worker_ids = [result.worker_id for result in results]
    if len(worker_ids) != len(set(worker_ids)):
        raise ValueError("task worker synthesis requires unique worker ids")
    ordered = tuple(sorted(results, key=lambda result: result.worker_id))
    workers = tuple(
        TaskWorkerContribution(
            worker_id=result.worker_id,
            status=result.status,
            summary=(
                result.summary[:_MAX_SUMMARY_CHARS]
                if result.summary is not None
                and result.status in {TaskWorkerStatus.SUCCEEDED, TaskWorkerStatus.ABSTAINED}
                else None
            ),
            evidence_refs=result.evidence_refs,
            caveats=result.caveats,
            usage=result.usage,
            terminal_reason=result.terminal_reason,
        )
        for result in ordered
    )
    evidence_refs = tuple(dict.fromkeys(ref for worker in workers for ref in worker.evidence_refs))
    return TaskWorkerSynthesis(
        answer_planning=answer_planning,
        workers=workers,
        total_usage=TaskWorkerUsage(
            tokens=sum(worker.usage.tokens for worker in workers),
            cost_microusd=sum(worker.usage.cost_microusd for worker in workers),
            tool_calls=sum(worker.usage.tool_calls for worker in workers),
        ),
        unique_evidence_refs=evidence_refs,
    )


__all__ = [
    "TaskWorkerContribution",
    "TaskWorkerSynthesis",
    "synthesize_task_worker_results",
]
