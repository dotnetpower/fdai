"""Durable ActionRun persistence tests for Thor + the composition seam."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.core.operational_planning.test_kinetic_proposal import _proposal

_RAW_TOPIC = "fdai.events"


class _FakeActionRunStore:
    """Minimal in-memory ActionRunStore double."""

    def __init__(self) -> None:
        self.saved: dict[str, ActionRun] = {}
        self.deleted: list[str] = []

    async def save(self, run: ActionRun) -> None:
        self.saved[run.correlation_id] = run

    async def load_active(self) -> list[ActionRun]:
        return list(self.saved.values())

    async def delete(self, correlation_id: str) -> None:
        self.deleted.append(correlation_id)
        self.saved.pop(correlation_id, None)


def test_action_run_dict_round_trip() -> None:
    proposal = _proposal()
    run = ActionRun(
        correlation_id="c",
        action_type="ops.restart-service",
        resource_id="r",
        state=ActionRunState.EXECUTING,
        verdict="auto",
        idempotency_key="action-1",
        shadow_mode=True,
        outcome="x",
        workflow_action={
            "process_id": "process-1",
            "step_id": "restart",
            "proposal_ref": "proposal-1",
        },
        kinetic_proposal=proposal.model_dump(mode="json"),
    )
    run.transition(ActionRunState.SUCCEEDED)
    back = ActionRun.from_dict(run.to_dict())
    assert back.correlation_id == run.correlation_id
    assert back.state == ActionRunState.SUCCEEDED
    assert back.history == run.history
    assert back.shadow_mode is True
    assert back.outcome == "x"
    assert back.idempotency_key == "action-1"
    assert back.workflow_action == run.workflow_action
    assert back.kinetic_proposal == run.kinetic_proposal


def _decision_case() -> dict[str, object]:
    proposal = _proposal()
    return {
        "case_id": "case-1",
        "process_id": proposal.process_id,
        "correlation_id": proposal.correlation_id,
        "context_snapshot_id": "context-1",
        "created_at": proposal.created_at.isoformat(),
        "selected_option_id": proposal.selected_option_id,
        "protected_objective_ids": ["objective-1"],
        "active_constraint_ids": [],
        "no_action_effects": [{"metric": "replicas", "value": 2}],
        "options": [
            {
                "option_id": proposal.selected_option_id,
                "action_type": proposal.plan.action_type_ref.name,
                "effects": [{"metric": "replicas", "value": 3}],
            }
        ],
        "evidence_refs": ["evidence-1"],
        "operational_plan": {
            "plan_id": proposal.operational_plan_id,
            "complete": True,
        },
    }


def _verdict() -> dict[str, object]:
    proposal = _proposal()
    return {
        "correlation_id": proposal.correlation_id,
        "action_type": proposal.plan.action_type_ref.name,
        "risk_verdict": "auto",
        "resource_id": proposal.target_resource_ref,
        "params": proposal.arguments(),
        "quorum_required": 2,
        "decision_case": _decision_case(),
        "kinetic_proposal": proposal.model_dump(mode="json"),
    }


def test_thor_preserves_valid_kinetic_proposal_without_raising_authority() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor, shadow_by_default=True)

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    assert run.verdict == "auto"
    assert run.quorum_required == 2
    assert run.shadow_mode is True
    assert run.kinetic_proposal == _proposal().model_dump(mode="json")
    executor.assert_not_awaited()
    assert thor.behavior_snapshot()["kinetic_proposal:validated"] == 1


def test_thor_persists_valid_hil_kinetic_proposal() -> None:
    store = _FakeActionRunStore()
    thor = Thor(state_store=store)
    verdict = _verdict()
    verdict["risk_verdict"] = "hil"

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.state is ActionRunState.HIL_PENDING
    assert store.saved[run.correlation_id].kinetic_proposal == run.kinetic_proposal


def test_durable_action_run_rejects_corrupt_kinetic_proposal() -> None:
    run = ActionRun(
        correlation_id="correlation-1",
        action_type="ops.scale",
        resource_id="workload-a",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
        kinetic_proposal=_proposal().model_dump(mode="json"),
    )
    raw = run.to_dict()
    assert isinstance(raw["kinetic_proposal"], dict)
    raw["kinetic_proposal"]["correlation_id"] = "substituted"

    with pytest.raises(ValueError, match="durable ActionRun kinetic proposal"):
        ActionRun.from_dict(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("correlation_id", "correlation-substituted"),
        ("action_type", "ops.restart-service"),
        ("resource_id", "workload-substituted"),
        ("params", {"replica_count": 99}),
    ),
)
def test_thor_denies_substituted_kinetic_verdict(field: str, value: object) -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    verdict[field] = value

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.verdict == "deny"
    assert run.kinetic_proposal is None
    executor.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("process_id",), "process-substituted"),
        (("selected_option_id",), "option-substituted"),
        (("correlation_id",), "correlation-substituted"),
        (("operational_plan", "plan_id"), "plan-substituted"),
        (("operational_plan", "complete"), False),
    ),
)
def test_thor_denies_substituted_planning_lineage(path: tuple[str, ...], value: object) -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    decision_case = deepcopy(verdict["decision_case"])
    assert isinstance(decision_case, dict)
    cursor = decision_case
    for key in path[:-1]:
        nested = cursor[key]
        assert isinstance(nested, dict)
        cursor = nested
    cursor[path[-1]] = value
    verdict["decision_case"] = decision_case

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.kinetic_proposal is None
    executor.assert_not_awaited()


def test_thor_denies_malformed_kinetic_proposal() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    proposal = deepcopy(verdict["kinetic_proposal"])
    assert isinstance(proposal, dict)
    proposal["mode"] = "enforce"
    verdict["kinetic_proposal"] = proposal

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.kinetic_proposal is None
    executor.assert_not_awaited()


def test_legacy_verdict_without_kinetic_proposal_is_unchanged() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)

    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "legacy-1",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-1",
            }
        )
    )

    assert run.state is ActionRunState.SUCCEEDED
    assert run.kinetic_proposal is None
    executor.assert_awaited_once()


def test_thor_deletes_terminal_run_from_store() -> None:
    store = _FakeActionRunStore()
    thor = Thor(state_store=store, shadow_by_default=True)

    async def _dispatch() -> ActionRun:
        return await thor.dispatch_verdict(
            {
                "correlation_id": "c",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resource_id": "vm-1",
            }
        )

    run = asyncio.run(_dispatch())
    assert run.state == ActionRunState.SUCCEEDED  # shadow success is terminal
    assert "c" in store.deleted  # terminal run removed from the durable store


def test_thor_persists_in_flight_hil_run() -> None:
    store = _FakeActionRunStore()
    thor = Thor(state_store=store)

    async def _dispatch() -> ActionRun:
        return await thor.dispatch_verdict(
            {
                "correlation_id": "c2",
                "action_type": "remediate.enable-encryption",
                "risk_verdict": "hil",
                "resource_id": "vm-2",
            }
        )

    run = asyncio.run(_dispatch())
    assert run.state == ActionRunState.HIL_PENDING
    assert "c2" in store.saved  # non-terminal run is persisted


def test_thor_rehydrate_restores_runs_and_locks() -> None:
    store = _FakeActionRunStore()
    pending = ActionRun(
        correlation_id="c3",
        action_type="remediate.enable-encryption",
        resource_id="vm-3",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )
    asyncio.run(store.save(pending))

    thor = Thor(state_store=store)
    restored = asyncio.run(thor.rehydrate())
    assert restored == 1
    assert "c3" in thor.action_runs
    assert "vm-3" in thor._resource_locks


def test_statestore_action_run_store_round_trip() -> None:
    store = StateStoreActionRunStore(store=InMemoryStateStore())
    run = ActionRun(
        correlation_id="c",
        action_type="ops.restart-service",
        resource_id="r",
        state=ActionRunState.EXECUTING,
        verdict="auto",
    )
    asyncio.run(store.save(run))
    active = asyncio.run(store.load_active())
    assert len(active) == 1
    assert active[0].correlation_id == "c"
    assert active[0].state == ActionRunState.EXECUTING
    assert active[0].idempotency_key == "c"

    asyncio.run(store.delete("c"))
    assert asyncio.run(store.load_active()) == []


def test_runtime_rehydrates_thor_on_run() -> None:
    store = _FakeActionRunStore()
    pending = ActionRun(
        correlation_id="c9",
        action_type="remediate.enable-encryption",
        resource_id="vm-9",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )
    asyncio.run(store.save(pending))

    provider = InMemoryEventBus()
    runtime = PantheonRuntime.build(
        provider=provider,
        raw_event_topic=_RAW_TOPIC,
        thor_state_store=store,
    )

    async def _drive() -> None:
        run_task = asyncio.create_task(runtime.run())
        for _ in range(20):
            await asyncio.sleep(0)
        await runtime.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup
            pass

    asyncio.run(_drive())
    thor = runtime.agents["Thor"]
    assert isinstance(thor, Thor)
    assert "c9" in thor.action_runs


def test_action_run_index_survives_concurrent_saves() -> None:
    # H3: concurrent index read-modify-write must not lose an entry (which
    # would orphan an in-flight run from rehydration).
    store = InMemoryStateStore()
    runstore = StateStoreActionRunStore(store=store)

    async def _run() -> set[str]:
        runs = [
            ActionRun(
                correlation_id=f"c{i}",
                action_type="restart",
                resource_id=f"r{i}",
                state=ActionRunState.VERDICTED,
                verdict="auto",
            )
            for i in range(25)
        ]
        await asyncio.gather(*(runstore.save(r) for r in runs))
        active = await runstore.load_active()
        return {r.correlation_id for r in active}

    got = asyncio.run(_run())
    assert got == {f"c{i}" for i in range(25)}


def test_load_active_skips_corrupt_row() -> None:
    # H4: one corrupt / schema-drifted row must not abort the whole
    # rehydration - the valid runs still restore.
    store = InMemoryStateStore()
    runstore = StateStoreActionRunStore(store=store)

    async def _run() -> list[str]:
        good = ActionRun(
            correlation_id="good",
            action_type="restart",
            resource_id="r1",
            state=ActionRunState.VERDICTED,
            verdict="auto",
        )
        await runstore.save(good)
        # Inject a corrupt row + index entry directly (missing required keys).
        await store.write_state("thor:run|bad", {"correlation_id": "bad"})
        await store.write_state("thor:active-index", {"ids": ["good", "bad"]})
        return [r.correlation_id for r in await runstore.load_active()]

    got = asyncio.run(_run())
    assert got == ["good"]  # bad row skipped, not fatal


def test_thor_evicts_terminal_runs_over_cap() -> None:
    # H8: the in-memory run map is bounded - terminal runs are evicted once
    # over the cap, active runs are always kept, health counts only active.
    thor = Thor(shadow_by_default=True)
    thor._max_retained_runs = 3

    async def _run() -> None:
        for i in range(6):
            await thor.dispatch_verdict(
                {
                    "correlation_id": f"c{i}",
                    "action_type": "restart",
                    "risk_verdict": "auto",
                    "resource_id": f"r{i}",
                }
            )

    asyncio.run(_run())
    assert len(thor.action_runs) <= 3  # bounded, not 6
    assert thor.health()["active_runs"] == 0  # all terminal
