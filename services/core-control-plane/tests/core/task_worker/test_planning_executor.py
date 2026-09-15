from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.conversation.answer_plan import AnswerSection
from fdai.core.conversation.answer_planning import (
    AnswerContribution,
    AnswerPlanningConfig,
    AnswerPlanningResult,
    GroundedFact,
    PlanningStatus,
)
from fdai.core.task_worker import (
    AnswerPlanningTaskWorkerExecutor,
    AttenuatedCapabilities,
    InMemoryTaskWorkerStore,
    TaskWorkerBudget,
    TaskWorkerContext,
    TaskWorkerPlanningResponse,
    TaskWorkerRequest,
    TaskWorkerRuntime,
    TaskWorkerRuntimeConfig,
    TaskWorkerStatus,
    TaskWorkerToolGateway,
    TaskWorkerUsage,
    synthesize_task_worker_results,
)


class _UnmeteredPlanningProvider:
    def __init__(self, contribution: AnswerContribution | None) -> None:
        self.contribution = contribution
        self.calls: list[tuple[str, str, int]] = []

    async def contribute(
        self,
        *,
        agent: str,
        prompt: str,
        max_tokens: int,
    ) -> AnswerContribution | None:
        self.calls.append((agent, prompt, max_tokens))
        return self.contribution


class _PlanningProvider:
    def __init__(
        self,
        contribution: AnswerContribution | None,
        *,
        tokens: int = 42,
        cost_microusd: int = 7,
    ) -> None:
        self.response = TaskWorkerPlanningResponse(contribution, tokens, cost_microusd)
        self.calls: list[tuple[str, str, int, int]] = []

    async def contribute_bounded(
        self,
        *,
        agent: str,
        prompt: str,
        max_tokens: int,
        max_cost_microusd: int,
    ) -> TaskWorkerPlanningResponse:
        self.calls.append((agent, prompt, max_tokens, max_cost_microusd))
        return self.response


def _gateway() -> TaskWorkerToolGateway:
    return TaskWorkerToolGateway(
        tools=(),
        capabilities=AttenuatedCapabilities(frozenset()),
        budget=TaskWorkerBudget(),
    )


def test_planning_executor_rejects_unmetered_provider_before_dispatch() -> None:
    provider = _UnmeteredPlanningProvider(None)

    with pytest.raises(TypeError, match="bounded.*usage"):
        AnswerPlanningTaskWorkerExecutor(
            provider=provider,  # type: ignore[arg-type] - exercise an invalid composition.
            contributor_agent="Heimdall",
        )

    assert provider.calls == []


async def test_planning_executor_reuses_provider_with_isolated_context_only() -> None:
    provider = _PlanningProvider(
        AnswerContribution(
            agent="Heimdall",
            facts=(GroundedFact("Observed bounded state.", "evidence:one"),),
            caveats=("Read-only result.",),
            suggested_sections=(AnswerSection.EVIDENCE,),
            evidence_refs=("evidence:one",),
            confidence=0.8,
        )
    )
    executor = AnswerPlanningTaskWorkerExecutor(
        provider=provider,
        contributor_agent="Heimdall",
    )

    output = await executor.execute(
        context=TaskWorkerContext(
            goal="Inspect the signal.",
            evidence_refs=("evidence:one",),
            constraints=("Read only.",),
            parent_trace_ref="trace:parent",
        ),
        tools=_gateway(),
        max_tokens=200,
        max_cost_microusd=10_000,
    )

    assert output.summary == "Observed bounded state."
    assert output.evidence_refs == ("evidence:one",)
    assert provider.calls[0][0] == "Heimdall"
    assert provider.calls[0][2] == 200
    assert provider.calls[0][3] == 10_000
    assert output.usage == TaskWorkerUsage(tokens=42, cost_microusd=7)
    prompt = provider.calls[0][1]
    assert "Inspect the signal." in prompt
    assert "evidence:one" in prompt
    assert "trace:parent" in prompt
    assert "parent transcript" not in prompt


async def test_planning_executor_maps_provider_abstention() -> None:
    executor = AnswerPlanningTaskWorkerExecutor(
        provider=_PlanningProvider(None),
        contributor_agent="Heimdall",
    )

    output = await executor.execute(
        context=TaskWorkerContext(
            goal="Inspect the signal.",
            evidence_refs=(),
            constraints=(),
            parent_trace_ref="trace:parent",
        ),
        tools=_gateway(),
        max_tokens=200,
        max_cost_microusd=10_000,
    )

    assert output.abstained is True
    assert output.evidence_refs == ()
    assert output.usage == TaskWorkerUsage(tokens=42, cost_microusd=7)


async def test_answer_planning_provider_runs_worker_and_returns_untrusted_synthesis() -> None:
    provider = _PlanningProvider(
        AnswerContribution(
            agent="Heimdall",
            facts=(GroundedFact("Observed bounded state.", "evidence:one"),),
            caveats=(),
            suggested_sections=(AnswerSection.EVIDENCE,),
            evidence_refs=("evidence:one",),
            confidence=0.8,
        )
    )
    runtime = TaskWorkerRuntime(
        store=InMemoryTaskWorkerStore(),
        executor=AnswerPlanningTaskWorkerExecutor(
            provider=provider,
            contributor_agent="Heimdall",
        ),
        tools=(),
        config=TaskWorkerRuntimeConfig(profile_allowed_tools=frozenset()),
    )
    now = datetime(2026, 7, 20, tzinfo=UTC)
    result = await runtime.run(
        TaskWorkerRequest(
            worker_id="worker-planning-integration",
            parent_trace_ref="trace:parent",
            cancellation_owner="operator-one",
            goal="Inspect the signal.",
            evidence_refs=("evidence:one",),
            constraints=("Read only.",),
            requested_tools=frozenset(),
            budget=TaskWorkerBudget(),
            created_at=now,
        ),
        parent_visible_tools=frozenset(),
    )
    planning = AnswerPlanningResult(
        status=PlanningStatus.COMPLETED,
        primary_agent="Forseti",
        consulted_agents=("Heimdall",),
        contributions=(),
        failures=(),
        elapsed_ms=1,
        unique_evidence_count=0,
        duplicate_evidence_count=0,
        conflicting_evidence_refs=(),
        covered_sections=(),
        estimated_added_tokens=0,
        budget=AnswerPlanningConfig(),
    )

    synthesis = synthesize_task_worker_results(
        answer_planning=planning,
        results=(result,),
    )

    assert synthesis.answer_planning is planning
    assert synthesis.workers[0].summary == "Observed bounded state."
    assert synthesis.workers[0].trusted is False
    assert synthesis.workers[0].usage == TaskWorkerUsage(tokens=42, cost_microusd=7)


@pytest.mark.parametrize("field", ["tokens", "cost_microusd"])
@pytest.mark.parametrize("value", [-1, True, 0.5, float("nan"), float("inf")])
def test_planning_response_rejects_invalid_usage(field, value) -> None:
    values = {"tokens": 0, "cost_microusd": 0, field: value}
    with pytest.raises(ValueError, match="non-negative integers"):
        TaskWorkerPlanningResponse(contribution=None, **values)


@pytest.mark.parametrize("contribution", [None, "unmetered"])
async def test_planning_executor_rejects_response_without_usage(contribution) -> None:
    class InvalidProvider:
        async def contribute_bounded(self, **kwargs):
            return contribution

    executor = AnswerPlanningTaskWorkerExecutor(
        provider=InvalidProvider(), contributor_agent="Heimdall"
    )
    with pytest.raises(TypeError, match="measured usage"):
        await executor.execute(
            context=TaskWorkerContext("Inspect.", (), (), "trace:parent"),
            tools=_gateway(),
            max_tokens=200,
            max_cost_microusd=10_000,
        )


async def test_empty_contribution_is_a_metered_abstention() -> None:
    provider = _PlanningProvider(
        AnswerContribution(
            agent="Heimdall",
            facts=(),
            caveats=("No admissible facts.",),
            suggested_sections=(),
            evidence_refs=(),
            confidence=0.0,
        )
    )
    executor = AnswerPlanningTaskWorkerExecutor(provider=provider, contributor_agent="Heimdall")

    output = await executor.execute(
        context=TaskWorkerContext("Inspect.", (), (), "trace:parent"),
        tools=_gateway(),
        max_tokens=200,
        max_cost_microusd=10_000,
    )

    assert output.abstained
    assert output.caveats == ("No admissible facts.",)
    assert output.usage == TaskWorkerUsage(tokens=42, cost_microusd=7)


@pytest.mark.parametrize(
    ("tokens", "cost", "max_tokens", "max_cost", "expected_status"),
    [
        (200, 7, 200, 7, TaskWorkerStatus.SUCCEEDED),
        (201, 7, 200, 7, TaskWorkerStatus.BUDGET_EXHAUSTED),
        (42, 8, 200, 7, TaskWorkerStatus.BUDGET_EXHAUSTED),
        (42, 1, 200, 0, TaskWorkerStatus.BUDGET_EXHAUSTED),
        (42, 0, 200, 0, TaskWorkerStatus.SUCCEEDED),
    ],
)
@pytest.mark.parametrize("abstained", [False, True])
async def test_measured_budget_result_persists_and_replay_does_not_call_provider(
    tokens, cost, max_tokens, max_cost, expected_status, abstained
) -> None:
    contribution = AnswerContribution(
        agent="Heimdall",
        facts=(GroundedFact("A short answer.", "evidence:one"),),
        caveats=(),
        suggested_sections=(),
        evidence_refs=("evidence:one",),
        confidence=0.8,
    )
    provider = _PlanningProvider(
        None if abstained else contribution, tokens=tokens, cost_microusd=cost
    )
    store = InMemoryTaskWorkerStore()

    def runtime() -> TaskWorkerRuntime:
        return TaskWorkerRuntime(
            store=store,
            executor=AnswerPlanningTaskWorkerExecutor(
                provider=provider, contributor_agent="Heimdall"
            ),
            tools=(),
        )

    request = TaskWorkerRequest(
        worker_id="worker-budget",
        parent_trace_ref="trace:parent",
        cancellation_owner="operator-one",
        goal="Inspect.",
        evidence_refs=("evidence:one",),
        constraints=(),
        requested_tools=frozenset(),
        budget=TaskWorkerBudget(max_tokens=max_tokens, max_cost_microusd=max_cost),
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    result = await runtime().run(request, parent_visible_tools=frozenset())
    if abstained and expected_status is TaskWorkerStatus.SUCCEEDED:
        expected_status = TaskWorkerStatus.ABSTAINED
    assert result.status is expected_status
    assert result.usage == TaskWorkerUsage(tokens=tokens, cost_microusd=cost)
    if expected_status is TaskWorkerStatus.BUDGET_EXHAUSTED:
        assert result.summary is None
        assert result.evidence_refs == ()
    snapshot = await store.get(request.worker_id)
    assert snapshot is not None and snapshot.result == result
    restarted = runtime()
    assert await restarted.recover_interrupted() == ()
    assert await restarted.run(request, parent_visible_tools=frozenset()) == result
    assert len(provider.calls) == 1
    assert provider.calls[0][2:] == (max_tokens, max_cost)
