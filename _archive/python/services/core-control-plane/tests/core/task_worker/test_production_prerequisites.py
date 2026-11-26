from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.conversation.answer_planning import AnswerContribution, GroundedFact
from fdai.core.task_worker import (
    AnswerPlanningTaskWorkerExecutor,
    AttenuatedCapabilities,
    InMemoryTaskWorkerStore,
    TaskWorkerBudget,
    TaskWorkerContext,
    TaskWorkerPlanningResponse,
    TaskWorkerRequest,
    TaskWorkerResult,
    TaskWorkerRuntime,
    TaskWorkerSnapshot,
    TaskWorkerStatus,
    TaskWorkerToolGateway,
    TaskWorkerUsage,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)


class _MeteredContributor:
    async def contribute_bounded(self, **_kwargs: object) -> TaskWorkerPlanningResponse:
        return TaskWorkerPlanningResponse(
            AnswerContribution(
                agent="Bragi",
                facts=(
                    GroundedFact("First recorded fact.", "evidence:one"),
                    GroundedFact("Second recorded fact.", "evidence:two"),
                ),
                caveats=(),
                suggested_sections=(),
                evidence_refs=("evidence:one", "evidence:two"),
                confidence=0.8,
            ),
            tokens=80,
            cost_microusd=50,
        )


async def test_metered_multiple_facts_obey_the_worker_summary_contract() -> None:
    executor = AnswerPlanningTaskWorkerExecutor(
        provider=_MeteredContributor(), contributor_agent="Bragi"
    )
    output = await executor.execute(
        context=TaskWorkerContext(
            "Read selected facts.", ("evidence:one", "evidence:two"), (), "trace:one"
        ),
        tools=TaskWorkerToolGateway(
            tools=(), capabilities=AttenuatedCapabilities(frozenset()), budget=TaskWorkerBudget()
        ),
        max_tokens=200,
        max_cost_microusd=100,
    )
    assert output.summary == "First recorded fact. Second recorded fact."
    assert output.usage == TaskWorkerUsage(tokens=80, cost_microusd=50)


async def test_recovery_finds_interrupted_work_behind_terminal_history() -> None:
    store = InMemoryTaskWorkerStore()
    request = TaskWorkerRequest(
        worker_id="worker:interrupted",
        parent_trace_ref="trace:one",
        cancellation_owner="person:one",
        goal="Read selected evidence.",
        evidence_refs=(),
        constraints=(),
        requested_tools=frozenset(),
        budget=TaskWorkerBudget(),
        created_at=NOW,
    )
    await store.create(
        TaskWorkerSnapshot(
            request=request,
            capabilities=AttenuatedCapabilities(frozenset()),
            status=TaskWorkerStatus.RUNNING,
            usage=TaskWorkerUsage(tokens=20, cost_microusd=15),
            updated_at=NOW,
        )
    )
    for index in range(1001):
        terminal_request = replace(request, worker_id=f"worker:terminal:{index}")
        result = TaskWorkerResult(
            worker_id=terminal_request.worker_id,
            parent_trace_ref=request.parent_trace_ref,
            status=TaskWorkerStatus.ABSTAINED,
            summary="No selected evidence.",
            evidence_refs=(),
            caveats=(),
            usage=TaskWorkerUsage(),
            terminal_reason="worker_abstained",
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
        )
        await store.create(
            TaskWorkerSnapshot(
                request=terminal_request,
                capabilities=AttenuatedCapabilities(frozenset()),
                status=result.status,
                usage=result.usage,
                updated_at=result.finished_at,
                result=result,
            )
        )
    runtime = TaskWorkerRuntime(
        store=store,
        executor=AnswerPlanningTaskWorkerExecutor(
            provider=_MeteredContributor(), contributor_agent="Bragi"
        ),
        tools=(),
        clock=lambda: NOW + timedelta(seconds=2),
    )
    recovered = await runtime.recover_interrupted()
    assert [result.worker_id for result in recovered] == [request.worker_id]
    assert recovered[0].terminal_reason == "runtime_restart_interrupted"
    assert recovered[0].usage == TaskWorkerUsage(tokens=20, cost_microusd=15)
