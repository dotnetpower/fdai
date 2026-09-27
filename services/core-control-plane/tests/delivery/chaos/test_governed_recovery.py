"""Governed chaos adapter: duplicate, concurrency, orphan, stop, rollback, and restart."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from typing import Any

import pytest
from fdai.core.chaos.run_state import ChaosRunState
from fdai.core.chaos.run_store import ChaosRunConflictError, ChaosRunStore
from fdai.core.recovery import RecoveryProbeKind
from fdai.delivery.chaos.governed_bindings import (
    ChaosApprovalEvidence,
)
from fdai.delivery.chaos.governed_records import governed_chaos_run_id
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import (
    ToolCallOutcome,
)

from tests.delivery.chaos.governed_doubles import (
    APPROVAL,
    SCENARIO_ID,
    Dispatcher,
    EvidenceCollector,
    Injector,
    LostLock,
    Planner,
    blocking_sleep,
    forbidden_signal,
    run_plan,
)
from tests.delivery.chaos.governed_fixtures import (
    audit_kinds,
    enforce_request,
    governed_fixture,
    run_state,
    seed_run,
)


class _ProcessStopped(BaseException):
    """Simulates the operator process exiting while a fault is live."""


async def _stop_process(_seconds: float) -> None:
    raise _ProcessStopped


class _InterleavingStateStore(InMemoryStateStore):
    """Yield between every durable read and write so concurrent adapters interleave."""

    def __init__(self, seed: int) -> None:
        super().__init__()
        self._random = random.Random(seed)  # noqa: S311 - deterministic interleaving seed

    async def _yield(self) -> None:
        for _ in range(self._random.randint(0, 3)):
            await asyncio.sleep(0)

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        await self._yield()
        return await super().read_state(key)

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        await self._yield()
        return await super().write_state_with_audit_if_absent(key, value, audit_entry)

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        await self._yield()
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


async def test_concurrent_duplicate_requests_inject_once_even_without_lock_exclusion() -> None:
    claim_losses = 0
    for seed in range(200):
        store = _InterleavingStateStore(seed)
        injector = Injector()
        replicas = [
            governed_fixture(injector=injector, state_store=store, lock=LostLock())
            for _ in range(2)
        ]

        outcomes = await asyncio.gather(
            *(replica.adapter.execute(enforce_request()) for replica in replicas),
            return_exceptions=True,
        )

        assert len(injector.injected) <= 1, f"seed {seed} injected twice"
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                assert isinstance(outcome, ChaosRunConflictError), outcome
            elif outcome.detail == "conflict:injection_claimed":
                assert outcome.outcome is ToolCallOutcome.PRECONDITION_FAILED
                claim_losses += 1
    assert claim_losses > 0


async def test_orphaned_run_blocks_new_requests_until_its_own_request_recovers() -> None:
    store = InMemoryStateStore()
    injector = Injector()
    orphaned = governed_fixture(injector=injector, state_store=store, sleeper=_stop_process)
    with pytest.raises(_ProcessStopped):
        await orphaned.adapter.execute(enforce_request())
    assert await run_state(orphaned) is ChaosRunState.OBSERVING

    fixture = governed_fixture(injector=injector, state_store=store)
    blocked = await fixture.adapter.execute(enforce_request(key="chaos-key-2"))
    resumed = await fixture.adapter.execute(enforce_request())
    allowed = await fixture.adapter.execute(enforce_request(key="chaos-key-3"))

    assert blocked.outcome is ToolCallOutcome.PRECONDITION_FAILED
    assert blocked.detail is not None and "conflicting_work_open" in blocked.detail
    blocked_run = governed_chaos_run_id("chaos-key-2", SCENARIO_ID, ("pod-a",))
    blocked_state = await ChaosRunStore(state_store=store).get(blocked_run)
    assert blocked_state is not None and blocked_state.state is ChaosRunState.DENIED
    assert resumed.detail == "resumed:recovered"
    assert allowed.outcome is ToolCallOutcome.SUCCEEDED
    assert injector.injected == ["pod-a", "pod-a"]
    assert "chaos.target.claim" in audit_kinds(fixture)


async def test_governed_adapter_replays_duplicate_request_without_reinjection() -> None:
    fixture = governed_fixture()

    first = await fixture.adapter.execute(enforce_request())
    second = await fixture.adapter.execute(enforce_request())

    assert first.outcome is ToolCallOutcome.SUCCEEDED
    assert second.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert second.already_existed is True
    assert second.receipt_ref == first.receipt_ref
    assert fixture.injector.injected == ["pod-a"]
    assert fixture.dispatcher.calls == ["restore"]
    assert fixture.planner.calls == 1


async def test_governed_adapter_stop_condition_forces_verified_recovery() -> None:
    fixture = governed_fixture(planner=Planner(run_plan(impact_guard=forbidden_signal)))

    receipt = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.STOPPED
    assert receipt.rollback_succeeded is True
    assert receipt.detail == "stopped:forbidden_signal:recovered"
    assert fixture.injector.stopped == ["pod-a"]
    assert fixture.dispatcher.calls == ["restore"]
    assert await run_state(fixture) is ChaosRunState.RECOVERED


async def test_governed_adapter_cancellation_recovers_before_propagating() -> None:
    fixture = governed_fixture(sleeper=blocking_sleep)
    task = asyncio.create_task(fixture.adapter.execute(enforce_request()))
    await asyncio.wait_for(fixture.injector.live.wait(), timeout=5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fixture.injector.stopped == ["pod-a"]
    assert fixture.dispatcher.calls == ["restore"]
    assert await run_state(fixture) is ChaosRunState.RECOVERED
    replay = await fixture.adapter.execute(enforce_request())
    assert replay.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert fixture.injector.injected == ["pod-a"]


@pytest.mark.parametrize(
    ("dispatcher", "collector", "detail"),
    [
        (Dispatcher(), EvidenceCollector(omit=RecoveryProbeKind.FAULT_ABSENT), "unscorable"),
        (Dispatcher(fail=True), EvidenceCollector(), "recovery_incomplete"),
    ],
)
async def test_governed_adapter_never_reports_unverified_recovery_as_success(
    dispatcher: Dispatcher,
    collector: EvidenceCollector,
    detail: str,
) -> None:
    fixture = governed_fixture(dispatcher=dispatcher, collector=collector)

    receipt = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert receipt.rollback_succeeded is False
    assert receipt.detail == f"escalated:{detail}"
    assert fixture.dispatcher.calls == ["restore"]
    assert await run_state(fixture) is ChaosRunState.ESCALATED


async def test_governed_adapter_reports_failed_fault_rollback_for_manual_recovery() -> None:
    fixture = governed_fixture(injector=Injector(stop_fails=True))

    receipt = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert receipt.rollback_succeeded is False
    assert receipt.detail == "failed:rollback_failed"
    assert await run_state(fixture) is ChaosRunState.FAILED


@pytest.mark.parametrize("approval", [APPROVAL, None])
async def test_governed_adapter_restart_resumes_recovery_without_reinjection(
    approval: ChaosApprovalEvidence | None,
) -> None:
    store = InMemoryStateStore()
    await seed_run(store, ChaosRunState.OBSERVING)
    fixture = governed_fixture(state_store=store, approval=approval)

    receipt = await fixture.adapter.execute(enforce_request())
    replay = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.STOPPED
    assert receipt.rollback_succeeded is True
    assert receipt.detail == "resumed:recovered"
    assert replay.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert fixture.injector.injected == []
    assert fixture.dispatcher.calls == ["restore"]


async def test_governed_adapter_escalates_in_flight_run_without_recovery_plan() -> None:
    store = InMemoryStateStore()
    await seed_run(store, ChaosRunState.INJECTING)
    fixture = governed_fixture(state_store=store, planner=Planner(None))

    receipt = await fixture.adapter.execute(enforce_request())

    assert receipt.outcome is ToolCallOutcome.FAILED
    assert receipt.rollback_succeeded is False
    assert receipt.detail == "escalated:run_plan_unavailable:injecting"
    assert await run_state(fixture) is ChaosRunState.INJECTING
    assert "chaos.run.escalation" in audit_kinds(fixture)
    assert fixture.injector.injected == []
