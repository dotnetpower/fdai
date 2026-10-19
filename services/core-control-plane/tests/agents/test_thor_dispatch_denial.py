"""A rejected dispatch observation must not trigger compensation for an unstarted action."""

import asyncio
from datetime import datetime
from typing import Any

import pytest
from fdai.agents._framework.bus import InMemoryBus, Payload
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.agents.vidar import Vidar
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.test_thor_dispatch_start import NOW
from tests.agents.test_thor_durable import _verdict


@pytest.mark.parametrize(
    "failure",
    [
        "record",
        "shadow",
        "development",
        "entry_authority",
        "authority_error",
        "missing_lock",
        "executor_false",
        "executor_error",
    ],
)
async def test_dispatch_denial_is_distinct_from_execution_failure(failure: str) -> None:
    await _assert_dispatch_outcome(failure, InMemoryStateStore())


async def _assert_dispatch_outcome(failure: str, state: StateStore) -> None:
    bus = InMemoryBus(registry=load_pantheon())
    calls: list[str] = []
    recorded = False

    class Store(StateStoreActionRunStore):
        async def record_dispatch_start(
            self, run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
        ) -> None:
            nonlocal recorded
            if failure == "record":
                raise OSError("observation unavailable")
            await super().record_dispatch_start(
                run, started_at=started_at, resource_lock_ref=resource_lock_ref
            )
            recorded = True

    class Host(Thor):
        def _revalidate_development_authority(self, run: ActionRun) -> None:
            if failure == "authority_error" and run.state is ActionRunState.EXECUTING:
                raise OSError("authority unavailable before executor I/O")
            if (
                failure == "development"
                and recorded
                or (failure == "entry_authority" and run.state is ActionRunState.EXECUTING)
            ):
                raise ValueError("authority changed before executor I/O")
            super()._revalidate_development_authority(run)

    async def executor(payload: dict[str, Any]) -> bool:
        calls.append("executor")
        if failure == "executor_error":
            raise OSError("injected executor failure")
        return False

    async def rollback(payload: dict[str, Any]) -> str:
        calls.append("rollback")
        return "rollback:unexpected"

    store = Store(store=state, clock=lambda: NOW)
    host = Host(
        bus=bus,
        executor=executor,
        state_store=store,
        shadow_required=lambda: failure == "shadow" and recorded,
        require_execution_resource_lock=failure == "missing_lock",
        clock=lambda: NOW,
    )
    recovery = Vidar(
        bus=bus,
        executors={"state_forward_only": rollback},
        allow_process_local_rollback=True,
    )
    bus.subscribe("object.action-run", "Vidar", recovery.on_typed_message)
    bus.subscribe("object.rollback", "Thor", host.on_typed_message)

    run = await host.dispatch_verdict(_verdict())

    if failure.startswith("executor_"):
        assert calls == ["executor", "rollback"]
        assert run.state is ActionRunState.ROLLED_BACK
        assert len(bus.messages_on("object.rollback")) == 1
    else:
        assert calls == []
        assert run.state is ActionRunState.DENY_DROPPED
        assert run.outcome == "dispatch_entry_rejected"
        assert not bus.messages_on("object.rollback")
        assert all(
            message.payload["state"] != "failed" for message in bus.messages_on("object.action-run")
        )
    assert run.resource_id not in host._resource_locks
    assert not run.resource_claimed
    if not failure.startswith("executor_"):
        restarted = Thor(
            bus=bus,
            executor=executor,
            state_store=StateStoreActionRunStore(store=state, clock=lambda: NOW),
            clock=lambda: NOW,
        )
        await restarted.rehydrate()
        replayed = await restarted.dispatch_verdict(_verdict())
        assert replayed.state is ActionRunState.DENY_DROPPED
        assert calls == [] and not bus.messages_on("object.rollback")


@pytest.mark.parametrize("cancelled", [False, True])
async def test_denial_publication_failure_is_explicit_and_releases_local_lock(
    cancelled: bool,
) -> None:
    class Bus(InMemoryBus):
        async def publish(self, principal: str, topic: str, payload: Payload) -> None:
            if topic == "object.action-run" and payload["state"] == "deny_dropped":
                if cancelled:
                    raise asyncio.CancelledError
                raise RuntimeError("denial publication unavailable")
            await super().publish(principal, topic, payload)

    class Store(StateStoreActionRunStore):
        async def record_dispatch_start(
            self, run: ActionRun, *, started_at: datetime, resource_lock_ref: str | None
        ) -> None:
            raise OSError("observation unavailable")

    async def executor(payload: dict[str, Any]) -> bool:
        pytest.fail("rejected dispatch reached the executor")

    store = Store(store=InMemoryStateStore(), clock=lambda: NOW)
    host = Thor(
        bus=Bus(registry=load_pantheon()),
        executor=executor,
        state_store=store,
        clock=lambda: NOW,
    )
    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        await host.dispatch_verdict(_verdict())
    retained = await store.load_active()
    assert len(retained) == 1 and retained[0].state is ActionRunState.DENY_DROPPED
    assert retained[0].terminal_published is False
    assert retained[0].resource_id not in host._resource_locks
