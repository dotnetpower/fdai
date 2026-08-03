"""Durable ActionRun persistence tests for Thor + the composition seam."""

from __future__ import annotations

import asyncio

from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

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
