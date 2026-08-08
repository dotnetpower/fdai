from __future__ import annotations

from datetime import UTC, datetime

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
    TaskWorkerRequest,
    TaskWorkerRuntime,
    TaskWorkerRuntimeConfig,
    TaskWorkerToolGateway,
    synthesize_task_worker_results,
)


class _PlanningProvider:
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


def _gateway() -> TaskWorkerToolGateway:
    return TaskWorkerToolGateway(
        tools=(),
        capabilities=AttenuatedCapabilities(frozenset()),
        budget=TaskWorkerBudget(),
    )


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
