"""Durable ActionRun persistence tests for Thor + the composition seam."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.provider_adapters import StateStoreActionRunStore
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai.shared.contracts.models import Autonomy
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


class _FailTerminalPublishBus:
    def __init__(self) -> None:
        self.fail_terminal_once = True
        self.payloads: list[dict[str, object]] = []

    async def publish(
        self,
        principal: str,
        topic: str,
        payload: dict[str, object],
    ) -> None:
        assert principal == "Thor"
        assert topic == "object.action-run"
        if payload.get("state") == "succeeded" and self.fail_terminal_once:
            self.fail_terminal_once = False
            raise RuntimeError("injected terminal publish failure")
        self.payloads.append(payload)


class _FailTerminalSaveStore(_FakeActionRunStore):
    async def save(self, run: ActionRun) -> None:
        if run.state is ActionRunState.SUCCEEDED:
            raise RuntimeError("injected terminal save failure")
        await super().save(run)


def test_action_run_dict_round_trip() -> None:
    proposal = _proposal()
    run = ActionRun(
        correlation_id=proposal.correlation_id,
        action_type=proposal.plan.action_type_ref.name,
        resource_id=proposal.target_resource_ref,
        state=ActionRunState.EXECUTING,
        verdict="auto",
        idempotency_key="action-1",
        params=proposal.arguments(),
        shadow_mode=True,
        outcome="x",
        decision_case=_decision_case(),
        operational_context={
            "snapshot_id": "context-1",
            "autonomy_ceiling": "shadow_only",
            "service_ids": [],
            "workload_ids": [],
            "objective_ids": [],
            "constraint_ids": [],
            "stale_sources": [],
            "conflicts": [],
        },
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
    assert back.operational_context == run.operational_context
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
        "resolved_autonomy_ceiling": "enforce_auto",
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


def test_thor_rechecks_live_authority_before_auto_execution() -> None:
    executor = AsyncMock(return_value=True)
    shadow_required = False
    thor = Thor(executor=executor, shadow_required=lambda: shadow_required)
    shadow_required = True

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    assert run.shadow_mode is True
    assert run.outcome == "shadow_success"
    executor.assert_not_awaited()


def test_thor_rechecks_live_authority_after_hil_approval() -> None:
    executor = AsyncMock(return_value=True)
    shadow_required = False
    thor = Thor(executor=executor, shadow_required=lambda: shadow_required)
    verdict = _verdict()
    verdict["risk_verdict"] = "hil"
    run = asyncio.run(thor.dispatch_verdict(verdict))
    shadow_required = True

    asyncio.run(
        thor.on_typed_message(
            "object.approval",
            {"correlation_id": run.correlation_id, "state": "approved"},
        )
    )

    assert run.shadow_mode is True
    assert run.outcome == "shadow_success"
    executor.assert_not_awaited()


def test_thor_preserves_shadow_only_ceiling_after_hil_approval() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    verdict["risk_verdict"] = "hil"
    verdict["resolved_autonomy_ceiling"] = "shadow_only"

    run = asyncio.run(thor.dispatch_verdict(verdict))
    asyncio.run(
        thor.on_typed_message(
            "object.approval",
            {"correlation_id": run.correlation_id, "state": "approved"},
        )
    )

    assert run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert run.shadow_mode is True
    assert run.outcome == "shadow_success"
    executor.assert_not_awaited()


def test_thor_expires_hil_without_executor_io() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    executor = AsyncMock(return_value=True)
    thor = Thor(
        executor=executor,
        clock=lambda: now,
        hil_timeout_seconds=60,
    )
    verdict = _verdict()
    verdict["risk_verdict"] = "hil"
    run = asyncio.run(thor.dispatch_verdict(verdict))
    thor._clock = lambda: now + timedelta(seconds=61)  # noqa: SLF001 - deterministic expiry

    expired = asyncio.run(thor.expire_pending_approvals())

    assert expired == 1
    assert run.state is ActionRunState.REJECTED
    assert run.outcome == "approval_expired"
    executor.assert_not_awaited()


@pytest.mark.parametrize("value", [None, "", "enforce"])
def test_thor_missing_or_invalid_ceiling_fails_closed(value: object) -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    if value is None:
        verdict.pop("resolved_autonomy_ceiling")
    else:
        verdict["resolved_autonomy_ceiling"] = value

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert run.shadow_mode is True
    executor.assert_not_awaited()


def test_thor_uses_restrictive_meet_of_top_level_and_context_ceilings() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    verdict["operational_context"] = {
        "snapshot_id": "context-shadow",
        "autonomy_ceiling": "shadow_only",
        "service_ids": [],
        "workload_ids": [],
        "objective_ids": [],
        "constraint_ids": [],
        "stale_sources": [],
        "conflicts": [],
    }

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert run.shadow_mode is True
    executor.assert_not_awaited()


def test_invalid_operational_context_forces_shadow() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    verdict = _verdict()
    verdict["operational_context"] = {"snapshot_id": object()}

    run = asyncio.run(thor.dispatch_verdict(verdict))

    assert run.resolved_autonomy_ceiling is Autonomy.SHADOW_ONLY
    assert run.operational_context is None
    executor.assert_not_awaited()


def test_thor_fails_closed_when_live_authority_provider_raises() -> None:
    executor = AsyncMock(return_value=True)

    def unavailable() -> bool:
        raise RuntimeError("authority unavailable")

    thor = Thor(executor=executor, shadow_required=unavailable)

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    assert run.shadow_mode is True
    assert run.outcome == "shadow_success"
    executor.assert_not_awaited()
    assert thor.behavior_snapshot()["authority:unavailable"] >= 1


def test_thor_requires_pre_execution_audit_when_configured() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(
        executor=executor,
        require_execution_audit=True,
    )

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "execution_audit_unavailable"
    executor.assert_not_awaited()


def test_thor_executes_only_after_pre_execution_audit_receipt() -> None:
    executor = AsyncMock(return_value=True)
    recorder = AsyncMock(return_value="audit-receipt-1")
    thor = Thor(
        executor=executor,
        execution_audit_recorder=recorder,
        require_execution_audit=True,
    )

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    assert run.state is ActionRunState.SUCCEEDED
    assert run.outcome == "command_accepted_verification_pending"
    assert run.execution_audit_receipt == "audit-receipt-1"
    recorder.assert_awaited_once_with(run)
    executor.assert_awaited_once()


def test_concurrent_duplicate_verdict_invokes_executor_once() -> None:
    calls = 0

    async def _execute(_context: object) -> bool:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return True

    thor = Thor(executor=_execute)

    async def _run() -> tuple[ActionRun, ActionRun]:
        return tuple(await asyncio.gather(*(thor.dispatch_verdict(_verdict()) for _ in range(2))))

    first, second = asyncio.run(_run())

    assert first is second
    assert calls == 1


def test_distinct_correlations_with_same_idempotency_key_execute_once() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    first = _verdict()
    first["idempotency_key"] = "stable-action-key"
    second = deepcopy(first)
    second["correlation_id"] = "different-correlation"
    second["kinetic_proposal"] = None
    second["decision_case"] = None

    first_run = asyncio.run(thor.dispatch_verdict(first))
    second_run = asyncio.run(thor.dispatch_verdict(second))

    assert second_run is first_run
    executor.assert_awaited_once()


def test_approval_and_verdict_redelivery_share_correlation_lock() -> None:
    calls = 0

    async def _execute(_context: object) -> bool:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return True

    thor = Thor(executor=_execute)
    verdict = _verdict()
    verdict["risk_verdict"] = "hil"
    verdict["resolved_autonomy_ceiling"] = "enforce_hil"
    run = asyncio.run(thor.dispatch_verdict(verdict))

    async def _race() -> None:
        await asyncio.gather(
            thor.dispatch_verdict(verdict),
            thor.on_typed_message(
                "object.approval",
                {"correlation_id": run.correlation_id, "state": "approved"},
            ),
        )

    asyncio.run(_race())

    assert run.state is ActionRunState.SUCCEEDED
    assert calls == 1


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


def test_durable_action_run_rejects_unbound_kinetic_proposal() -> None:
    """A contract-valid proposal from another run MUST NOT rehydrate into this one."""
    proposal = _proposal()
    run = ActionRun(
        correlation_id=proposal.correlation_id,
        action_type=proposal.plan.action_type_ref.name,
        resource_id=proposal.target_resource_ref,
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
        params=proposal.arguments(),
        decision_case=_decision_case(),
        kinetic_proposal=proposal.model_dump(mode="json"),
    )
    assert ActionRun.from_dict(run.to_dict()).kinetic_proposal == run.kinetic_proposal

    for field, value in (
        ("correlation_id", "correlation-substituted"),
        ("action_type", "ops.restart-service"),
        ("resource_id", "workload-substituted"),
        ("params", {"replica_count": 99}),
        ("decision_case", None),
    ):
        raw = run.to_dict()
        raw[field] = value
        with pytest.raises(ValueError, match="not bound to its run"):
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
                "resolved_autonomy_ceiling": "enforce_auto",
                "resource_id": "vm-1",
            }
        )
    )

    assert run.state is ActionRunState.SUCCEEDED
    assert run.kinetic_proposal is None
    executor.assert_awaited_once()


def test_executor_exception_outcome_omits_sensitive_message() -> None:
    async def failing_executor(_context: object) -> bool:
        raise RuntimeError("password=must-not-enter-audit")

    thor = Thor(executor=failing_executor)

    run = asyncio.run(
        thor.dispatch_verdict(
            {
                "correlation_id": "executor-error-1",
                "action_type": "ops.restart-service",
                "risk_verdict": "auto",
                "resolved_autonomy_ceiling": "enforce_auto",
                "resource_id": "vm-1",
            }
        )
    )

    assert run.state is ActionRunState.FAILED
    assert run.outcome == "executor_error:RuntimeError"


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


def test_thor_rehydrates_executing_run_as_unknown_without_reexecution() -> None:
    store = _FakeActionRunStore()
    executing = ActionRun(
        correlation_id="c-unknown",
        action_type="ops.restart-service",
        resource_id="vm-unknown",
        state=ActionRunState.EXECUTING,
        verdict="auto",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
    )
    asyncio.run(store.save(executing))
    executor = AsyncMock(return_value=True)
    thor = Thor(state_store=store, executor=executor)

    restored = asyncio.run(thor.rehydrate())

    assert restored == 1
    assert executing.state is ActionRunState.EXECUTION_UNKNOWN
    assert executing.outcome == "execution_state_unknown_after_restart"
    assert executing.shadow_mode is True
    assert "vm-unknown" in thor._resource_locks
    executor.assert_not_awaited()


def test_thor_rehydrates_unclaimed_duplicate_resource_runs_as_contended() -> None:
    store = _FakeActionRunStore()
    runs = (
        ActionRun(
            correlation_id="c-duplicate-1",
            action_type="ops.restart-service",
            resource_id="vm-duplicate",
            state=ActionRunState.VERDICTED,
            verdict="auto",
            resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
        ),
        ActionRun(
            correlation_id="c-duplicate-2",
            action_type="ops.restart-service",
            resource_id="vm-duplicate",
            state=ActionRunState.VERDICTED,
            verdict="auto",
            resolved_autonomy_ceiling=Autonomy.ENFORCE_AUTO,
        ),
    )
    for run in runs:
        asyncio.run(store.save(run))
    executor = AsyncMock(return_value=True)
    thor = Thor(state_store=store, executor=executor)

    restored = asyncio.run(thor.rehydrate())

    assert restored == 2
    assert {run.state for run in runs} == {ActionRunState.VERDICTED}
    assert {run.outcome for run in runs} == {"resource_claim_contended_after_restart"}
    executor.assert_not_awaited()


def test_rehydrated_execution_is_bounded_by_executor_timeout() -> None:
    store = _FakeActionRunStore()
    approved = ActionRun(
        correlation_id="c-timeout",
        action_type="ops.restart-service",
        resource_id="vm-timeout",
        state=ActionRunState.APPROVED,
        verdict="hil",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL,
    )
    asyncio.run(store.save(approved))

    async def _hang(_context: object) -> bool:
        await asyncio.sleep(60)
        return True

    thor = Thor(
        state_store=store,
        executor=_hang,
        executor_timeout_seconds=0.01,
    )

    restored = asyncio.run(thor.rehydrate())

    assert restored == 1
    assert approved.state is ActionRunState.EXECUTION_UNKNOWN
    assert approved.outcome == "executor_timeout"


def test_execution_unknown_accepts_only_explicit_rollback_result() -> None:
    run = ActionRun(
        correlation_id="c-rollback-unknown",
        action_type="ops.restart-service",
        resource_id="vm-rollback-unknown",
        state=ActionRunState.EXECUTION_UNKNOWN,
        verdict="auto",
    )
    thor = Thor()
    thor.action_runs[run.correlation_id] = run
    thor._resource_locks.add(str(run.resource_id))  # noqa: SLF001 - recovery boundary

    asyncio.run(
        thor.on_typed_message(
            "object.rollback",
            {
                "correlation_id": run.correlation_id,
                "state": "succeeded",
                "rollback_ref": "rollback:unknown",
            },
        )
    )

    assert run.state is ActionRunState.ROLLED_BACK
    assert run.outcome == "rollback_succeeded"
    assert str(run.resource_id) not in thor._resource_locks  # noqa: SLF001


def test_resolving_one_duplicate_unknown_run_keeps_shared_resource_locked() -> None:
    first = ActionRun(
        correlation_id="c-rollback-first",
        action_type="ops.restart-service",
        resource_id="vm-shared",
        state=ActionRunState.EXECUTION_UNKNOWN,
        verdict="auto",
    )
    second = ActionRun(
        correlation_id="c-rollback-second",
        action_type="ops.restart-service",
        resource_id="vm-shared",
        state=ActionRunState.EXECUTION_UNKNOWN,
        verdict="auto",
    )
    thor = Thor()
    thor.action_runs = {first.correlation_id: first, second.correlation_id: second}
    thor._resource_locks.add("vm-shared")  # noqa: SLF001 - recovery boundary

    asyncio.run(
        thor.on_typed_message(
            "object.rollback",
            {"correlation_id": first.correlation_id, "state": "succeeded"},
        )
    )

    assert first.state is ActionRunState.ROLLED_BACK
    assert second.state is ActionRunState.EXECUTION_UNKNOWN
    assert "vm-shared" in thor._resource_locks  # noqa: SLF001


def test_later_successful_rollback_closes_prior_rollback_failure() -> None:
    run = ActionRun(
        correlation_id="c-rollback-retry",
        action_type="ops.restart-service",
        resource_id="vm-rollback-retry",
        state=ActionRunState.ROLLBACK_FAILED,
        verdict="auto",
        terminal_published=True,
    )
    thor = Thor()
    thor.action_runs[run.correlation_id] = run
    thor._resource_locks.add(str(run.resource_id))  # noqa: SLF001 - recovery boundary

    asyncio.run(
        thor.on_typed_message(
            "object.rollback",
            {
                "correlation_id": run.correlation_id,
                "state": "succeeded",
                "rollback_ref": "rollback:retry",
            },
        )
    )

    assert run.state is ActionRunState.ROLLED_BACK
    assert run.rollback_ref == "rollback:retry"
    assert str(run.resource_id) not in thor._resource_locks  # noqa: SLF001


def test_terminal_publish_failure_remains_durable_for_restart_replay() -> None:
    store = _FakeActionRunStore()
    bus = _FailTerminalPublishBus()
    thor = Thor(bus=bus, state_store=store)

    with pytest.raises(RuntimeError, match="injected terminal publish failure"):
        asyncio.run(thor.dispatch_verdict(_verdict()))

    assert store.saved[_proposal().correlation_id].state is ActionRunState.SUCCEEDED

    restarted = Thor(bus=bus, state_store=store)
    restored = asyncio.run(restarted.rehydrate())

    assert restored == 1
    assert store.saved == {}
    assert any(payload["state"] == "succeeded" for payload in bus.payloads)


def test_terminal_save_failure_retains_resource_lock() -> None:
    store = _FailTerminalSaveStore()
    thor = Thor(state_store=store)

    with pytest.raises(RuntimeError, match="injected terminal save failure"):
        asyncio.run(thor.dispatch_verdict(_verdict()))

    assert _proposal().target_resource_ref in thor._resource_locks  # noqa: SLF001


def test_new_dispatch_continues_after_terminal_fence_repair() -> None:
    executor = AsyncMock(return_value=True)
    thor = Thor(executor=executor)
    old = ActionRun(
        correlation_id="old-correlation",
        action_type="ops.restart-service",
        resource_id=_proposal().target_resource_ref,
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        terminal_published=False,
    )
    thor.action_runs[old.correlation_id] = old
    thor._resource_locks.add(str(old.resource_id))  # noqa: SLF001 - recovery boundary

    run = asyncio.run(thor.dispatch_verdict(_verdict()))

    assert run.correlation_id == _proposal().correlation_id
    assert run is not old
    executor.assert_awaited_once()


def test_concurrent_new_correlations_cannot_bypass_terminal_resource_fence() -> None:
    calls = 0
    active = 0
    max_active = 0

    async def _execute(_context: object) -> bool:
        nonlocal active, calls, max_active
        calls += 1
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return True

    thor = Thor(executor=_execute)
    resource_id = _proposal().target_resource_ref
    old = ActionRun(
        correlation_id="old-correlation",
        action_type="ops.restart-service",
        resource_id=resource_id,
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        terminal_published=False,
    )
    thor.action_runs[old.correlation_id] = old
    thor._resource_locks.add(resource_id)  # noqa: SLF001 - recovery boundary
    first = _verdict()
    first["correlation_id"] = "new-correlation-1"
    first["kinetic_proposal"] = None
    first["decision_case"] = None
    second = deepcopy(first)
    second["correlation_id"] = "new-correlation-2"

    async def _run() -> tuple[ActionRun, ActionRun]:
        return tuple(
            await asyncio.gather(
                thor.dispatch_verdict(first),
                thor.dispatch_verdict(second),
            )
        )

    first_run, second_run = asyncio.run(_run())

    assert calls == 2
    assert max_active == 1
    assert {first_run.correlation_id, second_run.correlation_id} == {
        "new-correlation-1",
        "new-correlation-2",
    }


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


def test_statestore_completion_marker_blocks_stale_run_resurrection() -> None:
    state = InMemoryStateStore()
    first = StateStoreActionRunStore(store=state)
    stale_replica = StateStoreActionRunStore(store=state)
    run = ActionRun(
        correlation_id="completed-correlation",
        action_type="ops.restart-service",
        resource_id="completed-resource",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )

    asyncio.run(first.save(run))
    asyncio.run(first.delete(run.correlation_id))
    asyncio.run(stale_replica.save(run))

    assert asyncio.run(first.load_active()) == []


def test_statestore_rejects_stale_lifecycle_overwrite_before_terminal_publish() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    terminal = ActionRun(
        correlation_id="terminal-pending-publish",
        action_type="ops.restart-service",
        resource_id="terminal-resource",
        state=ActionRunState.SUCCEEDED,
        verdict="auto",
        outcome="command_accepted_verification_pending",
    )
    stale = ActionRun(
        correlation_id=terminal.correlation_id,
        action_type=terminal.action_type,
        resource_id=terminal.resource_id,
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )

    asyncio.run(store.save(terminal))
    asyncio.run(store.save(stale))
    active = asyncio.run(store.load_active())

    assert len(active) == 1
    assert active[0].state is ActionRunState.SUCCEEDED


def test_statestore_allows_explicit_recovery_and_lock_retry_transitions() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = ActionRun(
        correlation_id="recovery-transition",
        action_type="ops.restart-service",
        resource_id="recovery-resource",
        state=ActionRunState.ROLLBACK_FAILED,
        verdict="auto",
    )

    asyncio.run(store.save(run))
    run.transition(ActionRunState.ROLLED_BACK)
    run.outcome = "rollback_succeeded"
    asyncio.run(store.save(run))

    retry = ActionRun(
        correlation_id="lock-retry-transition",
        action_type="ops.restart-service",
        resource_id="retry-resource",
        state=ActionRunState.EXECUTING,
        verdict="auto",
    )
    asyncio.run(store.save(retry))
    retry.transition(ActionRunState.VERDICTED)
    retry.outcome = "execution_resource_temporarily_unavailable"
    asyncio.run(store.save(retry))

    states = {item.correlation_id: item.state for item in asyncio.run(store.load_active())}
    assert states == {
        "recovery-transition": ActionRunState.ROLLED_BACK,
        "lock-retry-transition": ActionRunState.VERDICTED,
    }


def test_statestore_resource_claim_serializes_replicas_and_releases_by_owner() -> None:
    state = InMemoryStateStore()
    first = StateStoreActionRunStore(store=state)
    second = StateStoreActionRunStore(store=state)
    first_run = ActionRun(
        correlation_id="correlation-1",
        action_type="ops.restart-service",
        resource_id="resource-shared",
        state=ActionRunState.VERDICTED,
        verdict="auto",
    )
    second_run = ActionRun(
        correlation_id="correlation-2",
        action_type="ops.restart-service",
        resource_id="resource-shared",
        state=ActionRunState.VERDICTED,
        verdict="auto",
    )

    async def _run() -> tuple[str, str, str, bool, bool]:
        first_claim, second_claim = await asyncio.gather(
            first.claim_resource(first_run),
            second.claim_resource(second_run),
        )
        duplicate_claim = await second.claim_resource(first_run)
        peer_release = await second.release_resource("resource-shared", "correlation-1")
        wrong_release = await second.release_resource("resource-shared", "correlation-2")
        owner_release = await first.release_resource("resource-shared", "correlation-1")
        repeated_release = await first.release_resource("resource-shared", "correlation-1")
        next_claim = await second.claim_resource(second_run)
        return (
            first_claim,
            second_claim,
            duplicate_claim,
            peer_release or wrong_release,
            owner_release and repeated_release and next_claim == "acquired",
        )

    assert asyncio.run(_run()) == (
        "acquired",
        "contended",
        "contended",
        False,
        True,
    )


def test_rehydrate_prefers_authoritative_claim_snapshot() -> None:
    state = InMemoryStateStore()
    store = StateStoreActionRunStore(store=state)
    run = ActionRun(
        correlation_id="claimed-hil",
        action_type="ops.restart-service",
        resource_id="claimed-resource",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL,
    )
    asyncio.run(store.save(run))
    assert asyncio.run(store.claim_resource(run)) == "acquired"

    thor = Thor(state_store=store)
    restored = asyncio.run(thor.rehydrate())

    assert restored == 1
    assert thor.action_runs[run.correlation_id].resource_claimed is True
    assert thor.action_runs[run.correlation_id].state is ActionRunState.HIL_PENDING


def test_scaling_replica_does_not_rehydrate_live_peer_claim() -> None:
    state = InMemoryStateStore()
    owner = StateStoreActionRunStore(store=state, owner_id="owner-1")
    peer = StateStoreActionRunStore(store=state, owner_id="owner-2")
    run = ActionRun(
        correlation_id="live-peer",
        action_type="ops.restart-service",
        resource_id="live-peer-resource",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL,
    )
    asyncio.run(owner.save(run))
    assert asyncio.run(owner.claim_resource(run)) == "acquired"

    assert asyncio.run(peer.load_active()) == []


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
