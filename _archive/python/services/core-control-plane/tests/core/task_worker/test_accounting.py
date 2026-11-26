from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fdai.core.conversation.answer_planning import (
    AnswerPlanningConfig,
    AnswerPlanningResult,
    PlanningStatus,
)
from fdai.core.task_worker import (
    AnswerPlanningTaskWorkerExecutor,
    AttenuatedCapabilities,
    InMemoryTaskWorkerStore,
    TaskWorkerBudget,
    TaskWorkerConflictError,
    TaskWorkerPlanningResponse,
    TaskWorkerRequest,
    TaskWorkerResult,
    TaskWorkerRuntime,
    TaskWorkerRuntimeConfig,
    TaskWorkerStatus,
    TaskWorkerToolGateway,
    TaskWorkerUsage,
    synthesize_task_worker_results,
)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"tokens": 1, "cost_microusd": 2},
        {"tokens": True, "cost_microusd": 0, "tool_calls": 0},
        {"tokens": 1.0, "cost_microusd": 0, "tool_calls": 0},
        {"tokens": 0, "cost_microusd": 0, "tool_calls": 0, "reserved_tokens": 10},
        {"tokens": 0, "cost_microusd": 0, "tool_calls": 0, "complete": "false"},
    ],
)
def test_malformed_durable_usage_cannot_turn_into_a_complete_zero(raw):
    with pytest.raises(ValueError):
        TaskWorkerUsage.from_dict(raw)


async def test_heartbeat_cannot_overwrite_an_inflight_reservation_with_old_usage():
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def checkpoint(usage):
        if not writes:
            entered.set()
            await release.wait()
        writes.append(usage)

    gateway = TaskWorkerToolGateway(
        tools=(),
        capabilities=AttenuatedCapabilities(frozenset()),
        budget=TaskWorkerBudget(),
        usage_checkpoint=checkpoint,
    )
    reserving = asyncio.create_task(gateway.reserve_planning(tokens=100, cost_microusd=20))
    await entered.wait()
    heartbeat = asyncio.create_task(gateway.checkpoint_usage())
    release.set()
    await asyncio.gather(reserving, heartbeat)
    assert len(writes) == 2
    assert all(not item.complete and item.reserved_tokens == 100 for item in writes)
    await gateway.record_planning_usage(tokens=80, cost_microusd=15)
    assert writes[-1] == TaskWorkerUsage(tokens=80, cost_microusd=15)


class _Provider:
    async def contribute_bounded(self, **kwargs):
        return TaskWorkerPlanningResponse(None, 0, 0)


def _request():
    return TaskWorkerRequest(
        worker_id="worker:one",
        parent_trace_ref="trace:one",
        cancellation_owner="person:one",
        goal="Read evidence.",
        evidence_refs=(),
        constraints=(),
        requested_tools=frozenset({"resolve_resource"}),
        budget=TaskWorkerBudget(),
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )


async def test_terminal_replay_cannot_reuse_a_now_denied_capability():
    store = InMemoryTaskWorkerStore()
    tool = SimpleNamespace(name="resolve_resource", side_effect_class="read")
    runtime = TaskWorkerRuntime(
        store=store,
        tools=(tool,),
        executor=AnswerPlanningTaskWorkerExecutor(provider=_Provider(), contributor_agent="Bragi"),
        config=TaskWorkerRuntimeConfig(profile_allowed_tools=frozenset({tool.name})),
    )
    result = await runtime.run(_request(), parent_visible_tools=frozenset({tool.name}))
    assert result.status is TaskWorkerStatus.ABSTAINED
    with pytest.raises(TaskWorkerConflictError, match="capabilities changed"):
        await runtime.run(_request(), parent_visible_tools=frozenset())
    assert (await store.get("worker:one")).result == result


def test_old_provider_and_store_seams_remain_usable_but_not_production_eligible():
    store = InMemoryTaskWorkerStore()
    legacy = SimpleNamespace(
        **{
            name: getattr(store, name)
            for name in (
                "create",
                "get",
                "transition",
                "heartbeat",
                "append_event",
                "list",
                "events",
            )
        }
    )
    executor = AnswerPlanningTaskWorkerExecutor(provider=_Provider(), contributor_agent="Bragi")
    TaskWorkerRuntime(store=legacy, executor=executor, tools=())
    with pytest.raises(TypeError, match="complete recovery"):
        TaskWorkerRuntime(store=legacy, executor=executor, tools=(), require_recoverable_store=True)
    with pytest.raises(TypeError, match="prepared"):
        AnswerPlanningTaskWorkerExecutor(
            provider=_Provider(), contributor_agent="Bragi", require_prepared=True
        )


def test_parent_synthesis_preserves_unknown_cost_and_suppresses_failed_summary():
    plan = AnswerPlanningResult(
        status=PlanningStatus.SKIPPED,
        primary_agent=None,
        consulted_agents=(),
        contributions=(),
        failures=(),
        elapsed_ms=0,
        unique_evidence_count=0,
        duplicate_evidence_count=0,
        conflicting_evidence_refs=(),
        covered_sections=(),
        estimated_added_tokens=0,
        budget=AnswerPlanningConfig(),
    )
    now = datetime(2026, 9, 15, tzinfo=UTC)
    usage = TaskWorkerUsage(reserved_tokens=100, reserved_cost_microusd=20, complete=False)
    result = TaskWorkerResult(
        "worker:one",
        "trace:one",
        TaskWorkerStatus.FAILED,
        "Do not publish this failed output.",
        (),
        (),
        usage,
        "runtime_restart_interrupted",
        now,
        now,
    )
    synthesis = synthesize_task_worker_results(answer_planning=plan, results=(result,))
    assert synthesis.total_usage == usage
    assert synthesis.workers[0].summary is None
    assert synthesis.to_dict()["total_usage"] == usage.to_dict()
