"""Vidar DR failover and rollback rehearsal contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.thor_preflight import PreflightSimulationResult
from fdai.agents._framework.vidar_dr import DR_CONTRACT_KIND, DR_OUTCOME_KIND
from fdai.agents._framework.vidar_rehearsal import REHEARSAL_KIND
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.vidar import Vidar
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
_EFFECT_REF = "sha256:" + "a" * 64
_CLOSURE_REF = "sha256:" + "b" * 64


def _safeguards(idempotency_key: str) -> dict[str, object]:
    return {
        "stop_condition": "stop when independent failover verification is missing",
        "tested_rollback_contract": "scripted:failback-tested",
        "blast_radius_limit": {"scope": "resource", "max_targets": 1},
        "dry_run_evidence": "declared_obligation",
        "dry_run_receipt": "sha256:" + "1" * 64,
        "logical_target_lock": "lock:resource:primary",
        "stable_idempotency_key": idempotency_key,
        "two_phase_audit_intent": "audit-intent:failover",
    }


def _failover_verdict(**overrides: Any) -> dict[str, Any]:
    idempotency_key = str(overrides.get("idempotency_key") or "idem-failover")
    payload: dict[str, Any] = {
        "producer_principal": "Forseti",
        "correlation_id": "corr-failover",
        "idempotency_key": idempotency_key,
        "action_type": "ops.failover-primary",
        "risk_verdict": "hil",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_HIL.value,
        "resource_id": "resource:primary",
        "rollback_contract": "scripted",
        "quorum_required": 2,
        "params": {
            "target_resource_ref": "resource:primary",
            "target_region": "eastus2",
            "reason": "incident classified failover",
        },
        "safeguards": _safeguards(idempotency_key),
    }
    payload.update(overrides)
    return payload


def _approval_for_run(run: Any) -> dict[str, Any]:
    return {
        "producer_principal": "Var",
        "kind": "action",
        "state": "approved",
        "correlation_id": run.correlation_id,
        "idempotency_key": f"approval:{run.idempotency_key}",
        "action_type": run.action_type,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "action_idempotency_key": run.idempotency_key,
        "resource_id": run.resource_id,
        "rollback_contract": run.rollback_contract,
        "approvers": ["one@example.com", "two@example.com"],
    }


def _effect_observation(run: Any) -> dict[str, Any]:
    return {
        "producer_principal": "Heimdall",
        "schema_version": "1.0.0",
        "event_type": "action.execution.effect_verified.v1",
        "correlation_id": run.correlation_id,
        "idempotency_key": f"effect:{run.idempotency_key}",
        "action_id": run.action_id,
        "action_type": run.action_type,
        "resource_id": run.resource_id,
        "action_idempotency_key": run.idempotency_key,
        "params": run.params,
        "effect_verification_ref": _EFFECT_REF,
        "execution_closure_ref": _CLOSURE_REF,
        "observed_at": (_NOW + timedelta(seconds=45)).isoformat(),
    }


class _PassingPreflight:
    def __init__(self) -> None:
        self.calls = 0

    async def simulate(self, _run: Any) -> PreflightSimulationResult:
        self.calls += 1
        return PreflightSimulationResult(
            outcome="passed",
            simulator_id="test-preflight",
            simulator_version="1",
        )


class _MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def _run_bridge_until(
    bridge: EventBusBridge,
    predicate: Callable[[], bool],
    *,
    steps: int = 2000,
) -> None:
    run_task = asyncio.create_task(bridge.run())
    try:
        for _ in range(steps):
            await asyncio.sleep(0)
            if predicate():
                return
        raise AssertionError("bridge condition was not observed")
    finally:
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - cleanup path
            pass


def _bridge() -> tuple[EventBusBridge, LocalEventBus]:
    provider = LocalEventBus()
    return EventBusBridge(provider=provider, registry=load_pantheon()), provider


async def _publish_failover_verdict_and_approval(
    bridge: EventBusBridge,
    thor: Thor,
    *,
    correlation_id: str,
) -> Any:
    await bridge.publish(
        "Forseti",
        "object.verdict",
        _failover_verdict(correlation_id=correlation_id, idempotency_key=f"idem:{correlation_id}"),
    )
    await _run_bridge_until(
        bridge,
        lambda: (
            correlation_id in thor.action_runs
            and thor.action_runs[correlation_id].state is ActionRunState.HIL_PENDING
        ),
    )
    run = thor.action_runs[correlation_id]
    await bridge.publish("Var", "object.approval", _approval_for_run(run))
    return run


def _wire_async_dr(
    *,
    thor: Thor,
    vidar: Vidar | None,
) -> tuple[EventBusBridge, LocalEventBus]:
    bridge, provider = _bridge()
    thor.bind_bus(bridge)
    bridge.subscribe("object.verdict", "Thor", thor.on_typed_message)
    bridge.subscribe("object.approval", "Thor", thor.on_typed_message)
    bridge.subscribe("object.rollback", "Thor", thor.on_typed_message)
    if vidar is not None:
        vidar.bind_bus(bridge)
        bridge.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    return bridge, provider


def test_async_dr_failover_waits_for_vidar_acceptance_before_single_executor_call() -> None:
    executed: list[str] = []

    async def executor(ctx: dict[str, Any]) -> bool:
        executed.append(ctx["run"].correlation_id)
        return True

    async def audit(_run: Any) -> str:
        return "audit:async"

    async def failback(_command: dict[str, Any]) -> str:
        return "failback:ready"

    thor = Thor(
        executor=executor,
        execution_audit_recorder=audit,
        preflight_simulator=_PassingPreflight(),
        clock=lambda: _NOW,
    )
    vidar = Vidar(
        executors={"scripted": failback},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=lambda: _NOW,
    )
    bridge, _ = _wire_async_dr(thor=thor, vidar=vidar)

    async def _drive() -> None:
        run = await _publish_failover_verdict_and_approval(
            bridge, thor, correlation_id="corr-async-accepted"
        )
        await _run_bridge_until(
            bridge,
            lambda: (
                run.state is ActionRunState.EFFECT_PENDING
                and executed == ["corr-async-accepted"]
                and thor.behavior_snapshot().get("dr_failover_contract:waiting", 0) == 1
            ),
        )

    asyncio.run(_drive())


def test_async_dr_failover_held_decision_denies_without_executor_call() -> None:
    executed: list[str] = []

    async def executor(ctx: dict[str, Any]) -> bool:
        executed.append(ctx["run"].correlation_id)
        return True

    thor = Thor(executor=executor, preflight_simulator=_PassingPreflight(), clock=lambda: _NOW)
    vidar = Vidar(
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=lambda: _NOW,
    )
    bridge, _ = _wire_async_dr(thor=thor, vidar=vidar)

    async def _drive() -> None:
        run = await _publish_failover_verdict_and_approval(
            bridge, thor, correlation_id="corr-async-held"
        )
        await _run_bridge_until(
            bridge,
            lambda: (
                run.state is ActionRunState.DENY_DROPPED
                and run.outcome == "dr_failover_contract_held:failback_executor_unbound"
            ),
        )

    asyncio.run(_drive())
    assert executed == []


def test_async_dr_failover_without_decision_times_out_with_injected_clock() -> None:
    clock = _MutableClock(_NOW)
    executed: list[str] = []

    async def executor(ctx: dict[str, Any]) -> bool:
        executed.append(ctx["run"].correlation_id)
        return True

    thor = Thor(executor=executor, preflight_simulator=_PassingPreflight(), clock=clock)
    bridge, _ = _wire_async_dr(thor=thor, vidar=None)

    async def _drive() -> None:
        run = await _publish_failover_verdict_and_approval(
            bridge, thor, correlation_id="corr-async-timeout"
        )
        await _run_bridge_until(
            bridge,
            lambda: (
                run.state is ActionRunState.APPROVED
                and run.outcome == "dr_failover_contract_pending"
            ),
        )
        clock.now = _NOW + timedelta(hours=2)
        assert await thor.expire_pending_approvals() == 1
        assert run.state is ActionRunState.DENY_DROPPED
        assert run.outcome == "dr_failover_contract_timeout"

    asyncio.run(_drive())
    assert executed == []


def test_async_dr_failover_restart_while_waiting_resumes_after_vidar_acceptance() -> None:
    clock = _MutableClock(_NOW)
    executed: list[str] = []
    state = InMemoryStateStore()
    provider = LocalEventBus()

    async def executor(ctx: dict[str, Any]) -> bool:
        executed.append(ctx["run"].correlation_id)
        return True

    async def audit(_run: Any) -> str:
        return "audit:restart"

    first_thor = Thor(
        executor=executor,
        execution_audit_recorder=audit,
        preflight_simulator=_PassingPreflight(),
        state_store=StateStoreActionRunStore(state),
        clock=clock,
    )
    first_bridge = EventBusBridge(provider=provider, registry=load_pantheon())
    first_thor.bind_bus(first_bridge)
    first_bridge.subscribe("object.verdict", "Thor", first_thor.on_typed_message)
    first_bridge.subscribe("object.approval", "Thor", first_thor.on_typed_message)

    async def _approve_without_vidar() -> None:
        run = await _publish_failover_verdict_and_approval(
            first_bridge, first_thor, correlation_id="corr-async-restart"
        )
        await _run_bridge_until(
            first_bridge,
            lambda: (
                run.state is ActionRunState.APPROVED
                and run.outcome == "dr_failover_contract_pending"
            ),
        )

    asyncio.run(_approve_without_vidar())

    restarted_thor = Thor(
        executor=executor,
        execution_audit_recorder=audit,
        preflight_simulator=_PassingPreflight(),
        state_store=StateStoreActionRunStore(state),
        clock=clock,
    )

    async def failback(_command: dict[str, Any]) -> str:
        return "failback:ready"

    vidar = Vidar(
        executors={"scripted": failback},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=clock,
    )
    bridge = EventBusBridge(provider=provider, registry=load_pantheon())
    restarted_thor.bind_bus(bridge)
    vidar.bind_bus(bridge)
    bridge.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bridge.subscribe("object.rollback", "Thor", restarted_thor.on_typed_message)
    asyncio.run(restarted_thor.rehydrate())

    async def _resume_after_restart() -> None:
        await _run_bridge_until(
            bridge,
            lambda: (
                restarted_thor.action_runs["corr-async-restart"].state
                is ActionRunState.EFFECT_PENDING
                and executed == ["corr-async-restart"]
            ),
        )

    asyncio.run(_resume_after_restart())


def test_vidar_dr_failover_requires_contract_audit_rollback_and_effect_verification() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    executed: list[str] = []
    audits: list[str] = []
    preflight = _PassingPreflight()

    async def executor(ctx: dict[str, Any]) -> bool:
        executed.append(ctx["run"].correlation_id)
        return True

    async def audit(run: Any) -> str:
        audits.append(run.correlation_id)
        return "audit:failover"

    async def failback(_command: dict[str, Any]) -> str:
        return "failback:ready"

    thor = Thor(
        bus=bus,
        executor=executor,
        execution_audit_recorder=audit,
        preflight_simulator=preflight,
        clock=lambda: _NOW,
    )
    vidar = Vidar(
        bus=bus,
        executors={"scripted": failback},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=lambda: _NOW,
    )
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    run = asyncio.run(thor.dispatch_verdict(_failover_verdict()))
    assert run.state is ActionRunState.HIL_PENDING

    asyncio.run(thor.on_typed_message("object.approval", _approval_for_run(run)))

    assert executed == ["corr-failover"]
    assert audits == ["corr-failover"]
    assert preflight.calls == 1
    assert run.state is ActionRunState.EFFECT_PENDING
    decisions = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == DR_CONTRACT_KIND
    ]
    assert decisions[-1]["decision"] == "accepted"
    assert decisions[-1]["failback_contract"] == "scripted"
    assert decisions[-1]["expected_effect_digest"].startswith("sha256:")

    asyncio.run(
        thor.on_typed_message("object.recovery-effect-observation", _effect_observation(run))
    )

    assert run.state is ActionRunState.SUCCEEDED
    outcomes = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == DR_OUTCOME_KIND
    ]
    assert len(outcomes) == 1
    assert outcomes[0]["recovery_time_seconds"] == 45.0
    assert vidar.health()["mttr_samples"]["count"] == 1


def test_vidar_dr_failover_outcome_uses_persisted_contract_after_restart() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    store = InMemoryStateStore()

    async def executor(_ctx: dict[str, Any]) -> bool:
        return True

    async def audit(_run: Any) -> str:
        return "audit:restart-dr"

    async def failback(_command: dict[str, Any]) -> str:
        return "failback:ready"

    thor = Thor(
        bus=bus,
        executor=executor,
        execution_audit_recorder=audit,
        preflight_simulator=_PassingPreflight(),
    )
    vidar = Vidar(
        bus=bus,
        executors={"scripted": failback},
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=lambda: _NOW,
    )
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    run = asyncio.run(thor.dispatch_verdict(_failover_verdict(correlation_id="corr-restart-dr")))
    asyncio.run(thor.on_typed_message("object.approval", _approval_for_run(run)))
    assert [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == DR_CONTRACT_KIND
    ][-1]["decision"] == "accepted"

    restarted = Vidar(
        bus=bus,
        executors={"scripted": failback},
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=lambda: _NOW + timedelta(seconds=45),
    )
    asyncio.run(
        restarted.on_typed_message(
            "object.action-run",
            {
                **run.to_dict(),
                "producer_principal": "Thor",
                "state": "succeeded",
                "action_run_identity": action_run_identity_digest(run.to_dict()),
                "effect_verification_ref": _EFFECT_REF,
                "observed_at": (_NOW + timedelta(seconds=45)).isoformat(),
            },
        )
    )

    outcomes = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == DR_OUTCOME_KIND
    ]
    assert outcomes[-1]["action_run_identity"] == action_run_identity_digest(run.to_dict())
    assert outcomes[-1]["recovery_time_seconds"] == 45.0
    assert restarted.health()["mttr_samples"]["count"] == 1


def test_vidar_dr_outcome_retry_after_broker_publish_failure() -> None:
    class _FailOnceOutcomeBus(InMemoryBus):
        def __init__(self) -> None:
            super().__init__(registry=load_pantheon())
            self.failed = False

        async def publish(
            self,
            principal: str,
            topic: str,
            payload: dict[str, object],
        ) -> None:
            if payload.get("kind") == DR_OUTCOME_KIND and not self.failed:
                self.failed = True
                raise RuntimeError("injected DR outcome publish failure")
            await super().publish(principal, topic, payload)

    bus = _FailOnceOutcomeBus()
    vidar = Vidar(bus=bus, clock=lambda: _NOW)
    outcome = {
        "producer_principal": "Vidar",
        "kind": DR_OUTCOME_KIND,
        "correlation_id": "corr-dr-retry",
        "idempotency_key": "dr-outcome:retry",
        "action_run_identity": "sha256:" + "1" * 64,
        "action_type": "ops.failover-primary",
        "resource_id": "resource:primary",
        "recovery_time_seconds": 45.0,
    }

    try:
        asyncio.run(vidar._publish_dr_outcome(dict(outcome)))  # noqa: SLF001
    except RuntimeError:
        pass
    asyncio.run(vidar._publish_dr_outcome(dict(outcome)))  # noqa: SLF001

    outcomes = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == DR_OUTCOME_KIND
    ]
    assert len(outcomes) == 1
    assert {
        key: outcomes[0][key]
        for key in (
            "kind",
            "correlation_id",
            "idempotency_key",
            "action_run_identity",
            "recovery_time_seconds",
        )
    } == {
        key: outcome[key]
        for key in (
            "kind",
            "correlation_id",
            "idempotency_key",
            "action_run_identity",
            "recovery_time_seconds",
        )
    }
    assert vidar.health()["mttr_samples"]["count"] == 1


def test_vidar_holds_dr_failover_when_failback_executor_is_unbound() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    executed: list[str] = []

    async def executor(ctx: dict[str, Any]) -> bool:
        executed.append(ctx["run"].correlation_id)
        return True

    thor = Thor(bus=bus, executor=executor, preflight_simulator=_PassingPreflight())
    vidar = Vidar(
        bus=bus,
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        clock=lambda: _NOW,
    )
    bus.subscribe("object.action-run", "Vidar", vidar.on_typed_message)
    bus.subscribe("object.rollback", "Thor", thor.on_typed_message)

    run = asyncio.run(thor.dispatch_verdict(_failover_verdict(correlation_id="corr-held")))
    asyncio.run(thor.on_typed_message("object.approval", _approval_for_run(run)))

    assert executed == []
    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "dr_failover_contract_held:failback_executor_unbound"
    holds = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == DR_CONTRACT_KIND
    ]
    assert holds[-1]["decision"] == "held"
    assert holds[-1]["reason"] == "failback_executor_unbound"


class _RehearsalPort:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.commands: list[dict[str, Any]] = []

    async def rehearse(self, command: dict[str, Any]) -> dict[str, str]:
        self.commands.append(dict(command))
        return {
            "outcome": self.outcome,
            "reason": f"rehearsal_{self.outcome}",
            "rehearsal_version": "1.0.0",
        }


class _HangingRehearsalPort:
    async def rehearse(self, _command: dict[str, Any]) -> dict[str, str]:
        await asyncio.Event().wait()
        return {"outcome": "passed"}


class _FailOnceRehearsalBus(InMemoryBus):
    def __init__(self) -> None:
        super().__init__(registry=load_pantheon())
        self.failed = False

    async def publish(
        self,
        principal: str,
        topic: str,
        payload: dict[str, object],
    ) -> None:
        if payload.get("kind") == REHEARSAL_KIND and not self.failed:
            self.failed = True
            raise RuntimeError("injected rehearsal publish failure")
        await super().publish(principal, topic, payload)


def test_vidar_records_bounded_non_mutating_rehearsal_receipts() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    port = _RehearsalPort("passed")
    store = InMemoryStateStore()
    vidar = Vidar(
        bus=bus,
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_port=port,
        rollback_rehearsal_cadence=timedelta(seconds=1),
        clock=lambda: _NOW,
    )

    asyncio.run(vidar.maintenance_tick())

    assert port.commands == [
        {
            "mode": "dry_run",
            "action_type": "ops.failover-primary",
            "rollback_contract": "scripted",
        }
    ]
    receipts = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == REHEARSAL_KIND
    ]
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "passed"
    assert receipts[0]["receipt_digest"].startswith("sha256:")
    assert vidar.health()["rollback_rehearsal"]["passed"] == 1


def test_vidar_retries_unpublished_rehearsal_without_waiting_for_cadence() -> None:
    bus = _FailOnceRehearsalBus()
    port = _RehearsalPort("passed")
    store = InMemoryStateStore()
    vidar = Vidar(
        bus=bus,
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_port=port,
        rollback_rehearsal_cadence=timedelta(days=30),
        clock=lambda: _NOW,
    )

    try:
        asyncio.run(vidar.maintenance_tick())
    except RuntimeError:
        pass
    asyncio.run(vidar.maintenance_tick())

    assert len(port.commands) == 1
    receipts = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == REHEARSAL_KIND
    ]
    assert len(receipts) == 1
    rows = asyncio.run(store.read_states("pantheon/vidar/rehearsal/", limit=10))
    assert len(rows) == 1
    assert rows[0]["published"] is True
    assert vidar.health()["rollback_rehearsal"]["passed"] == 1


def test_vidar_rehydrates_and_publishes_unpublished_rehearsal_receipt() -> None:
    failing_bus = _FailOnceRehearsalBus()
    port = _RehearsalPort("passed")
    store = InMemoryStateStore()
    first = Vidar(
        bus=failing_bus,
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_port=port,
        rollback_rehearsal_cadence=timedelta(days=30),
        clock=lambda: _NOW,
    )
    try:
        asyncio.run(first.maintenance_tick())
    except RuntimeError:
        pass

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Vidar(
        bus=bus,
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_cadence=timedelta(days=30),
        clock=lambda: _NOW + timedelta(days=1),
    )

    asyncio.run(restarted.recover_rollbacks())

    receipts = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == REHEARSAL_KIND
    ]
    assert len(receipts) == 1
    assert receipts[0]["recorded_at"] == _NOW.isoformat()
    assert restarted.health()["rollback_rehearsal"]["passed"] == 1


def test_vidar_rehearsal_failure_lowers_readiness_without_authority_change() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    vidar = Vidar(
        bus=bus,
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_port=_RehearsalPort("failed"),
        rollback_rehearsal_cadence=timedelta(seconds=1),
        clock=lambda: _NOW,
    )

    asyncio.run(vidar.maintenance_tick())

    health = vidar.health()
    assert health["rollback_rehearsal"]["failed"] == 1
    assert health["dr_readiness_score"]["evidence_state"] == "measured_with_rehearsal_failures"
    assert health["dr_readiness_score"]["coverage_ratio"] == 0.0


def test_vidar_rehearsal_timeout_records_visible_hold() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    vidar = Vidar(
        bus=bus,
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_port=_HangingRehearsalPort(),
        rollback_rehearsal_cadence=timedelta(seconds=1),
        rollback_rehearsal_timeout_seconds=0.01,
        clock=lambda: _NOW,
    )

    asyncio.run(vidar.maintenance_tick())

    receipts = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == REHEARSAL_KIND
    ]
    assert receipts[0]["outcome"] == "held"
    assert receipts[0]["reason"] == "rehearsal_port_timeout"
    assert vidar.behavior_snapshot()["rollback_rehearsal:timeout"] == 1
    assert vidar.health()["rollback_rehearsal"]["evidence_state"] == "unbound"


def test_vidar_rehydrates_durable_rehearsal_receipts_into_health() -> None:
    store = InMemoryStateStore()
    first = Vidar(
        bus=InMemoryBus(registry=load_pantheon()),
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_port=_RehearsalPort("failed"),
        rollback_rehearsal_cadence=timedelta(days=30),
        clock=lambda: _NOW,
    )
    asyncio.run(first.maintenance_tick())

    restarted = Vidar(
        state_store=store,
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_cadence=timedelta(days=30),
        clock=lambda: _NOW + timedelta(days=1),
    )
    asyncio.run(restarted.recover_rollbacks())

    health = restarted.health()
    assert health["rollback_rehearsal"]["failed"] == 1
    assert health["dr_readiness_score"]["evidence_state"] == "measured_with_rehearsal_failures"
    assert health["dr_readiness_score"]["coverage_ratio"] == 0.0


def test_vidar_unbound_rehearsal_port_records_visible_noop() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    vidar = Vidar(
        bus=bus,
        executors={"scripted": lambda _cmd: asyncio.sleep(0, result="rollback:unused")},
        state_store=InMemoryStateStore(),
        rollback_contracts_by_action_type={"ops.failover-primary": "scripted"},
        rollback_rehearsal_cadence=timedelta(seconds=1),
        clock=lambda: _NOW,
    )

    asyncio.run(vidar.maintenance_tick())

    receipts = [
        msg.payload
        for msg in bus.messages_on("object.rollback")
        if msg.payload.get("kind") == REHEARSAL_KIND
    ]
    assert receipts[0]["outcome"] == "held"
    assert receipts[0]["reason"] == "rehearsal_port_unbound"
    assert vidar.health()["rollback_rehearsal"]["evidence_state"] == "unbound"
