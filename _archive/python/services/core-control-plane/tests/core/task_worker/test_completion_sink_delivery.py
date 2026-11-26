"""Focused tests for durable detached-session task-worker completion sink delivery."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.task_worker.models import (
    TaskWorkerBudget,
    TaskWorkerOutput,
    TaskWorkerRequest,
    TaskWorkerStatus,
    TaskWorkerUsage,
)
from fdai.core.task_worker.runtime import TaskWorkerRuntime, TaskWorkerRuntimeConfig
from fdai.core.task_worker.store import InMemoryTaskWorkerStore
from fdai.core.task_worker.tools import TaskWorkerToolGateway
from fdai.delivery.task_worker_completion_sink import (
    COMPLETION_FAILURE_EVENT_KIND,
    DetachedSessionTaskWorkerCompletionSink,
    DetachedWorkerCompletionEnvelope,
    InMemoryDetachedSessionReplyLedger,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _request(worker_id: str = "worker-sink-1") -> TaskWorkerRequest:
    return TaskWorkerRequest(
        worker_id=worker_id,
        parent_trace_ref="trace-parent-1",
        cancellation_owner="operator-a",
        goal="Inspect recorded VM state.",
        evidence_refs=("inv:vm-1",),
        constraints=("read-only",),
        requested_tools=frozenset(),
        budget=TaskWorkerBudget(),
        created_at=NOW,
    )


class _CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        *,
        context: object,
        tools: TaskWorkerToolGateway,
        max_tokens: int,
        max_cost_microusd: int,
    ) -> TaskWorkerOutput:
        del context, tools, max_tokens, max_cost_microusd
        self.calls += 1
        return TaskWorkerOutput(
            summary="Recorded VM state is healthy.",
            evidence_refs=("inv:vm-1",),
            caveats=(),
            usage=TaskWorkerUsage(tokens=120, cost_microusd=400, tool_calls=0),
        )


class _FlakyReplySink:
    def __init__(self, *, fail_first: bool = True) -> None:
        self.fail_first = fail_first
        self.delivered: list[DetachedWorkerCompletionEnvelope] = []

    async def deliver_worker_completion(self, envelope: DetachedWorkerCompletionEnvelope) -> None:
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("detached reply channel temporarily unavailable")
        self.delivered.append(envelope)


async def test_completion_sink_delivers_once_and_preserves_untrusted_boundary() -> None:
    store = InMemoryTaskWorkerStore()
    executor = _CountingExecutor()
    ledger = InMemoryDetachedSessionReplyLedger()
    sink = DetachedSessionTaskWorkerCompletionSink(reply_sink=ledger)
    runtime = TaskWorkerRuntime(
        store=store,
        executor=executor,
        tools=(),
        config=TaskWorkerRuntimeConfig(),
        completion_sink=sink,
        clock=lambda: NOW,
    )

    result = await runtime.run(_request("worker-once"), parent_visible_tools=frozenset())
    assert result.status is TaskWorkerStatus.SUCCEEDED
    assert result.trusted is False
    assert executor.calls == 1

    delivered = ledger.get("worker-once")
    assert delivered is not None
    assert delivered.trusted is False
    assert delivered.execution_authority == "none"
    assert delivered.summary == "Recorded VM state is healthy."

    duplicate_receipt = await sink.deliver(result)
    assert duplicate_receipt.delivered is True
    assert duplicate_receipt.duplicate is True
    assert len(ledger.list_delivered()) == 1


async def test_sink_failure_appends_event_without_rewriting_or_rerunning_terminal_result() -> None:
    store = InMemoryTaskWorkerStore()
    executor = _CountingExecutor()
    flaky = _FlakyReplySink(fail_first=True)
    sink = DetachedSessionTaskWorkerCompletionSink(reply_sink=flaky, store=store)
    runtime = TaskWorkerRuntime(
        store=store,
        executor=executor,
        tools=(),
        config=TaskWorkerRuntimeConfig(),
        completion_sink=sink,
        clock=lambda: NOW,
    )

    result = await runtime.run(_request("worker-sink-fail"), parent_visible_tools=frozenset())
    assert result.status is TaskWorkerStatus.SUCCEEDED
    assert result.summary == "Recorded VM state is healthy."
    assert executor.calls == 1

    snapshot = await store.get("worker-sink-fail", owner="operator-a")
    assert snapshot is not None
    assert snapshot.status is TaskWorkerStatus.SUCCEEDED
    assert snapshot.result == result

    events = await store.events("worker-sink-fail", owner="operator-a")
    assert [event.kind for event in events] == [
        "worker.created",
        "worker.started",
        "worker.succeeded",
        COMPLETION_FAILURE_EVENT_KIND,
    ]
    assert events[-1].details == (("error", "RuntimeError"),)

    retry_receipt = await sink.deliver(result)
    assert retry_receipt.delivered is True
    assert retry_receipt.duplicate is False
    assert executor.calls == 1
    assert len(flaky.delivered) == 1
