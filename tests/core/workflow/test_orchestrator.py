"""WorkflowOrchestrator (shadow) tests.

Covers the P1 shadow run: plan approvals, walk the compiled Runbook with a
non-mutating step executor, and audit the whole run. Proves the shadow
invariant (no mutation), the audit trail shape, idempotent Process ids, and
that a gated step carries its resolved approver assignment into the audit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import (
    ProcessStatus,
    ShadowWorkflowStepExecutor,
    WorkflowOrchestrator,
    derive_process_id,
)
from fdai.shared.contracts.models import (
    Autonomy,
    CeilingByTier,
    CeilingRole,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    TierCeiling,
    Workflow,
    WorkflowStep,
    WorkflowStepKind,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessSnapshot,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TRIGGER_TS = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


def _group_mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="grp-readers",
        contributor_group_id="grp-contributors",
        approver_group_id="grp-approvers",
        owner_group_id="grp-owners",
        break_glass_group_id="grp-break-glass",
    )


def _matrix():  # type: ignore[no-untyped-def]
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "hil_approval",
                "routes": {
                    "hil_approval": {
                        "trust_tier": "a1_hil_approval",
                        "primary": "teams-hil-prd",
                        "fallback": ["slack-hil-prd"],
                    }
                },
            }
        }
    )


def _action(name: str, *, ceiling: CeilingByTier | None = None) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        description="Test action.",
        ceiling_by_tier=ceiling,
    )


_GATED = _action(
    "ops.gated",
    ceiling=CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
    ),
)
_AUTO = _action(
    "remediate.auto",
    ceiling=CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.CONTRIBUTOR),
    ),
)
_ACTION_TYPES = {a.name: a for a in (_GATED, _AUTO)}


def _workflow(*, default_mode: Mode = Mode.SHADOW) -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="sample-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=default_mode,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[
            WorkflowStep(id="auto_step", action_type_ref="remediate.auto"),
            WorkflowStep(id="gated_step", action_type_ref="ops.gated"),
        ],
    )


def _orchestrator(audit: InMemoryStateStore) -> WorkflowOrchestrator:
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    return WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
    )


async def test_shadow_run_succeeds_and_judges_every_step() -> None:
    audit = InMemoryStateStore()
    run = await _orchestrator(audit).run(
        _workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS
    )
    assert run.status is ProcessStatus.SUCCEEDED
    assert [r.outcome for r in run.step_results] == [
        RunbookStepOutcome.SUCCESS,
        RunbookStepOutcome.SUCCESS,
    ]
    assert all(r.reason == "shadow_judge_and_log" for r in run.step_results)


async def test_audit_trail_shape() -> None:
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    kinds = [row["entry"]["action_kind"] for row in audit.audit_entries]
    # process-plan, then one workflow.step per step, then the runner terminal.
    assert kinds == [
        "workflow.process-plan",
        "workflow.step",
        "workflow.step",
        "runbook.terminal",
    ]
    # Every workflow entry is shadow-mode.
    for row in audit.audit_entries:
        entry = row["entry"]
        if entry["action_kind"].startswith("workflow."):
            assert entry["mode"] == "shadow"


async def test_declared_mode_recorded_even_when_enforce() -> None:
    # An enforce-declared workflow still runs in shadow here (the executor
    # structurally cannot mutate), but the declared mode is surfaced in the
    # process-plan audit so a silent "declared enforce, ran shadow" is visible
    # to a reviewer rather than masked by the hardcoded run mode.
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(
        _workflow(default_mode=Mode.ENFORCE),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
    )
    plan_entries = [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.process-plan"
    ]
    assert len(plan_entries) == 1
    assert plan_entries[0]["declared_mode"] == "enforce"
    # The run itself is still shadow - no mutation path exists.
    assert plan_entries[0]["mode"] == "shadow"


class _RecordingActionDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def dispatch(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        return "proposal-1"


class _FailingActionDispatcher(_RecordingActionDispatcher):
    def __init__(self, *, fail_step: str) -> None:
        super().__init__()
        self.fail_step = fail_step

    async def dispatch(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        step = kwargs["step"]
        if isinstance(step, RunbookStep) and step.id == self.fail_step:
            raise RuntimeError("synthetic failure")
        return f"proposal:{step.id}" if isinstance(step, RunbookStep) else "proposal"


class _AcceptingOutcomeVerifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def verify(self, **kwargs: str) -> bool:
        self.calls.append(dict(kwargs))
        return True


def _compensated_workflow() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="compensated-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="iac.plan"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=21,
            min_samples=40,
            min_accuracy=0.98,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="apply_first",
                action_type_ref="remediate.auto",
                compensated_by="ops.gated",
            ),
            WorkflowStep(id="apply_second", action_type_ref="remediate.auto"),
        ],
    )


async def test_enforce_action_step_republishes_through_dispatcher() -> None:
    audit = InMemoryStateStore()
    dispatcher = _RecordingActionDispatcher()
    verifier = _AcceptingOutcomeVerifier()
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        action_dispatcher=dispatcher,
        outcome_verifier=verifier,
    )

    first_wait = await orchestrator.run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )
    second_wait = await orchestrator.run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "action.auto_step.status": "verified",
            "action.auto_step.receipt_ref": "receipt:auto",
        },
        mode=Mode.ENFORCE,
    )
    run = await orchestrator.run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "action.auto_step.status": "verified",
            "action.auto_step.receipt_ref": "receipt:auto",
            "action.gated_step.status": "verified",
            "action.gated_step.receipt_ref": "receipt:gated",
        },
        mode=Mode.ENFORCE,
    )

    assert first_wait.status is ProcessStatus.WAITING
    assert second_wait.status is ProcessStatus.WAITING
    assert run.status is ProcessStatus.SUCCEEDED
    assert run.mode == "enforce"
    assert len(dispatcher.calls) == 2
    assert run.step_results[-1].reason == "action_effect_verified"
    assert [call["outcome"] for call in verifier.calls] == ["succeeded", "succeeded"]
    workflow_entries = [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"].startswith("workflow.")
    ]
    assert all(entry["mode"] == "enforce" for entry in workflow_entries)


async def test_enforce_action_step_fails_without_dispatcher() -> None:
    audit = InMemoryStateStore()

    run = await _orchestrator(audit).run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )

    assert run.status is ProcessStatus.FAILED
    assert run.step_results[0].reason == "enforce_action_dispatcher_not_configured"


async def test_enforce_failure_dispatches_reverse_compensation_and_waits_for_receipt() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    dispatcher = _FailingActionDispatcher(fail_step="apply_second")
    verifier = _AcceptingOutcomeVerifier()
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        action_dispatcher=dispatcher,
        outcome_verifier=verifier,
    )

    first_wait = await orchestrator.run(
        _compensated_workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )
    recovering = await orchestrator.run(
        _compensated_workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "action.apply_first.status": "verified",
            "action.apply_first.receipt_ref": "receipt:apply:1",
        },
        mode=Mode.ENFORCE,
    )
    assert first_wait.status is ProcessStatus.WAITING
    assert recovering.status is ProcessStatus.COMPENSATING
    assert [call["step"].id for call in dispatcher.calls] == [
        "apply_first",
        "apply_second",
        "compensate_apply_first",
    ]
    events = await process_store.events(recovering.process_id)
    compensation = [
        event for event in events if event.kind is ProcessEventKind.COMPENSATION_STARTED
    ]
    assert len(compensation) == 1
    assert compensation[0].payload["compensates_step_id"] == "apply_first"
    dispatched = [
        event for event in events if event.kind is ProcessEventKind.COMPENSATION_DISPATCHED
    ]
    assert len(dispatched) == 1
    assert dispatched[0].payload["proposal_ref"] == "proposal:compensate_apply_first"

    completed = await orchestrator.run(
        _compensated_workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "compensation.apply_first.status": "verified",
            "compensation.apply_first.receipt_ref": "receipt:rollback:1",
        },
        mode=Mode.ENFORCE,
    )

    assert completed.status is ProcessStatus.COMPENSATED
    assert len(dispatcher.calls) == 3
    final_events = await process_store.events(completed.process_id)
    assert final_events[-1].kind is ProcessEventKind.COMPENSATION_COMPLETED
    assert final_events[-1].payload["receipt_refs"] == ["receipt:rollback:1"]
    assert verifier.calls[-1]["outcome"] == "succeeded"


async def test_compensation_failure_closes_process_as_recovery_incomplete() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    verifier = _AcceptingOutcomeVerifier()
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        action_dispatcher=_FailingActionDispatcher(fail_step="apply_second"),
        outcome_verifier=verifier,
    )
    workflow = _compensated_workflow()
    await orchestrator.run(
        workflow,
        target_resource_id="res-2",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )
    await orchestrator.run(
        workflow,
        target_resource_id="res-2",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "action.apply_first.status": "verified",
            "action.apply_first.receipt_ref": "receipt:apply:1",
        },
        mode=Mode.ENFORCE,
    )
    failed = await orchestrator.run(
        workflow,
        target_resource_id="res-2",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "compensation.apply_first.status": "failed",
            "compensation.apply_first.receipt_ref": "receipt:rollback:failed",
        },
        mode=Mode.ENFORCE,
    )

    assert failed.status is ProcessStatus.FAILED
    events = await process_store.events(failed.process_id)
    assert events[-1].kind is ProcessEventKind.PROCESS_FAILED
    assert events[-1].payload["recovery_incomplete"] is True


async def test_action_outcome_context_cannot_advance_without_verifier() -> None:
    audit = InMemoryStateStore()
    dispatcher = _RecordingActionDispatcher()
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        action_dispatcher=dispatcher,
    )
    await orchestrator.run(
        _workflow(),
        target_resource_id="res-unverified",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )

    held = await orchestrator.run(
        _workflow(),
        target_resource_id="res-unverified",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "action.auto_step.status": "verified",
            "action.auto_step.receipt_ref": "forged-receipt",
        },
        mode=Mode.ENFORCE,
    )

    assert held.status is ProcessStatus.WAITING
    assert held.step_results[-1].reason == "waiting_for_action_outcome_verifier"


async def test_compensating_snapshot_without_intent_fails_closed() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    workflow = _compensated_workflow()
    process_id = derive_process_id(
        workflow_name=workflow.name,
        target_resource_id="res-corrupt",
        trigger_ts=_TRIGGER_TS,
    )
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=process_id,
            workflow_ref=workflow.name,
            workflow_version=str(workflow.version),
            status=ProcessStatus.COMPENSATING,
            current_step="compensate_missing",
            target_resource_id="res-corrupt",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="corr-corrupt",
        ),
        event=ProcessEvent(
            event_id="event-corrupt",
            process_id=process_id,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key=f"{process_id}:created",
            recorded_at=_TRIGGER_TS,
            correlation_id="corr-corrupt",
        ),
    )
    assert snapshot.status is ProcessStatus.COMPENSATING
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        action_dispatcher=_RecordingActionDispatcher(),
        outcome_verifier=_AcceptingOutcomeVerifier(),
    )

    failed = await orchestrator.run(
        workflow,
        target_resource_id="res-corrupt",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        correlation_id="corr-corrupt",
        mode=Mode.ENFORCE,
    )

    assert failed.status is ProcessStatus.FAILED
    events = await process_store.events(process_id)
    assert events[-1].payload["reason"] == "compensation_intent_missing"


async def test_gated_step_carries_approver_assignment_into_audit() -> None:
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    step_rows = [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.step"
    ]
    by_step = {e["step_id"]: e for e in step_rows}
    assert by_step["gated_step"]["requires_approval"] is True
    assert by_step["gated_step"]["required_role"] == "Approver"
    assert by_step["gated_step"]["approver_group"] == "grp-approvers"
    assert by_step["gated_step"]["notify_channels"] == ["teams-hil-prd", "slack-hil-prd"]
    # The auto step is not a gate.
    assert by_step["auto_step"]["requires_approval"] is False
    assert by_step["auto_step"]["approver_group"] is None


async def test_process_id_is_idempotent() -> None:
    audit = InMemoryStateStore()
    orch = _orchestrator(audit)
    run_a = await orch.run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    run_b = await orch.run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    assert run_a.process_id == run_b.process_id
    # A different target yields a different id.
    run_c = await orch.run(_workflow(), target_resource_id="res-2", trigger_ts=_TRIGGER_TS)
    assert run_c.process_id != run_a.process_id


def test_derive_process_id_is_stable() -> None:
    a = derive_process_id(workflow_name="wf", target_resource_id="r", trigger_ts=_TRIGGER_TS)
    b = derive_process_id(workflow_name="wf", target_resource_id="r", trigger_ts=_TRIGGER_TS)
    assert a == b


async def test_unknown_action_type_step_fails_closed() -> None:
    # The executor branch for an ActionType absent from the catalog: it audits
    # and reports FAILURE rather than pretending success.
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id="p-1",
            workflow_ref="wf",
            workflow_version="1.0.0",
            status=ProcessStatus.RUNNING,
            current_step="ghost",
            target_resource_id="res-1",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="corr-1",
        ),
        event=ProcessEvent(
            event_id="event-create",
            process_id="p-1",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="p-1:create",
            recorded_at=_TRIGGER_TS,
            correlation_id="corr-1",
        ),
    )
    executor = ShadowWorkflowStepExecutor(
        process_id="p-1",
        action_types=_ACTION_TYPES,
        audit_store=audit,
        approvals={},
        process_store=process_store,
        snapshot=snapshot,
    )
    result = await executor.execute(
        runbook_id="wf", step=RunbookStep(id="ghost", action_type="ops.absent")
    )
    assert result.outcome is RunbookStepOutcome.FAILURE
    assert result.reason == "unknown_action_type"


class _StubGuard:
    """Deterministic guard evaluator for tests - returns a fixed verdict and
    records the calls it saw."""

    def __init__(self, *, verdict: bool) -> None:
        self._verdict = verdict
        self.calls: list[tuple[str, str]] = []

    async def evaluate(self, *, rule_id: str, step_id: str, process_id: str) -> bool:
        self.calls.append((rule_id, step_id))
        return self._verdict


def _workflow_with_guard() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="guarded-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[
            WorkflowStep(
                id="guarded",
                action_type_ref="remediate.auto",
                guard_rule_ref="some.guard.rule",
            ),
        ],
    )


def _orchestrator_with_guard(
    audit: InMemoryStateStore, guard: _StubGuard | None
) -> WorkflowOrchestrator:
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    return WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=guard,
    )


def _guarded_step_entry(audit: InMemoryStateStore) -> dict:
    return next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.step" and row["entry"]["step_id"] == "guarded"
    )


async def test_guard_pass_proceeds_and_records() -> None:
    audit = InMemoryStateStore()
    guard = _StubGuard(verdict=True)
    run = await _orchestrator_with_guard(audit, guard).run(
        _workflow_with_guard(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS
    )
    assert run.status is ProcessStatus.SUCCEEDED
    assert guard.calls == [("some.guard.rule", "guarded")]
    entry = _guarded_step_entry(audit)
    assert entry["guard_evaluated"] is True
    assert entry["guard_passed"] is True
    assert run.step_results[0].reason == "shadow_judge_and_log"


async def test_guard_block_is_a_shadow_noop_not_a_failure() -> None:
    audit = InMemoryStateStore()
    guard = _StubGuard(verdict=False)
    run = await _orchestrator_with_guard(audit, guard).run(
        _workflow_with_guard(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS
    )
    # A blocked guard is a judged no-op; the run still succeeds.
    assert run.status is ProcessStatus.SUCCEEDED
    assert run.step_results[0].reason == "guard_blocked_shadow_noop"
    entry = _guarded_step_entry(audit)
    assert entry["guard_evaluated"] is True
    assert entry["guard_passed"] is False


async def test_no_evaluator_leaves_guard_unevaluated() -> None:
    audit = InMemoryStateStore()
    await _orchestrator_with_guard(audit, None).run(
        _workflow_with_guard(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS
    )
    entry = _guarded_step_entry(audit)
    assert entry["guard_rule_ref"] == "some.guard.rule"
    assert entry["guard_evaluated"] is False
    assert entry["guard_passed"] is None


async def test_process_persisted_in_runtime_snapshot_and_journal() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
    )
    run = await orchestrator.run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    snapshot = await process_store.get(run.process_id)
    assert snapshot is not None
    assert snapshot.workflow_ref == "sample-flow"
    assert snapshot.status is ProcessStatus.SUCCEEDED
    assert snapshot.target_resource_id == "res-1"
    assert snapshot.current_step == ""
    assert len(await process_store.events(run.process_id)) == 7


def _workflow_with_params() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="param-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="object.drift"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        steps=[
            WorkflowStep(
                id="p",
                action_type_ref="remediate.auto",
                params={
                    "reason": "drift on ${event.resource_ref} (${event.event_type})",
                    "unknown": "${event.nope}",
                    "count": 3,
                    "enabled": True,
                },
            ),
        ],
    )


def _param_entry(audit: InMemoryStateStore) -> dict:
    return next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.step" and row["entry"]["step_id"] == "p"
    )


async def test_params_substituted_from_event_context() -> None:
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(
        _workflow_with_params(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={"event.event_type": "object.drift"},
    )
    params = _param_entry(audit)["params"]
    # Known tokens substituted from context; base event.resource_ref works too.
    assert params["reason"] == "drift on res-1 (object.drift)"
    # An unknown token is left verbatim (visible, not silently blanked).
    assert params["unknown"] == "${event.nope}"
    # Non-string values pass through unchanged.
    assert params["count"] == 3
    assert params["enabled"] is True


async def test_params_default_empty_when_absent() -> None:
    audit = InMemoryStateStore()
    await _orchestrator(audit).run(_workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS)
    step_rows = [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"]["action_kind"] == "workflow.step"
    ]
    assert all(row["params"] == {} for row in step_rows)


def _control_workflow() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="architecture-review",
        version="1.0.0",
        trigger=WorkflowTrigger(
            kind=WorkflowTriggerKind.SIGNAL,
            signal_type="architecture.review.requested",
        ),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=30,
            min_accuracy=0.98,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="domain_reviews",
                kind=WorkflowStepKind.PARALLEL,
                branches=["security", "privacy", "reliability"],
            ),
            WorkflowStep(
                id="evidence",
                kind=WorkflowStepKind.WAIT,
                wait_for="evidence.updated",
                timeout_seconds=120,
            ),
            WorkflowStep(
                id="board_approval",
                kind=WorkflowStepKind.APPROVAL,
                approval_role=CeilingRole.APPROVER,
                quorum=2,
                timeout_seconds=120,
            ),
            WorkflowStep(
                id="board_decision",
                kind=WorkflowStepKind.DECISION,
                outcomes=["approved", "conditional", "rejected"],
            ),
        ],
    )


async def test_control_workflow_waits_and_resumes_same_process() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    planner = WorkflowApprovalPlanner(
        action_types=_ACTION_TYPES,
        group_mapping=_group_mapping(),
        matrix=_matrix(),
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
    )
    workflow = _control_workflow()

    evidence_wait = await orchestrator.run(
        workflow,
        target_resource_id="scope-1",
        trigger_ts=_TRIGGER_TS,
    )
    approval_wait = await orchestrator.run(
        workflow,
        target_resource_id="scope-1",
        trigger_ts=_TRIGGER_TS,
        context={"signal.evidence.updated": "received"},
    )
    decision_wait = await orchestrator.run(
        workflow,
        target_resource_id="scope-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "signal.evidence.updated": "received",
            "approval.board_approval.operator-a": "approved",
            "approval.board_approval.operator-b": "approved",
        },
    )
    completed = await orchestrator.run(
        workflow,
        target_resource_id="scope-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "signal.evidence.updated": "received",
            "approval.board_approval.operator-a": "approved",
            "approval.board_approval.operator-b": "approved",
            "decision.board_decision": "conditional",
        },
    )

    assert {run.process_id for run in (evidence_wait, approval_wait, decision_wait, completed)} == {
        completed.process_id
    }
    assert [run.status for run in (evidence_wait, approval_wait, decision_wait, completed)] == [
        ProcessStatus.WAITING,
        ProcessStatus.WAITING,
        ProcessStatus.WAITING,
        ProcessStatus.SUCCEEDED,
    ]
    assert completed.replayed is True
    events = await process_store.events(completed.process_id)
    kinds = [event.kind for event in events]
    assert ProcessEventKind.STEP_WAITING in kinds
    assert ProcessEventKind.APPROVAL_REQUESTED in kinds
    assert ProcessEventKind.APPROVAL_RECORDED in kinds
    assert ProcessEventKind.DECISION_RECORDED in kinds
    assert kinds.count(ProcessEventKind.PARALLEL_BRANCH_STARTED) == 3
    assert kinds.count(ProcessEventKind.PARALLEL_BRANCH_COMPLETED) == 3
    assert kinds[-1] is ProcessEventKind.PROCESS_COMPLETED


async def test_approval_requires_distinct_quorum_and_excludes_requester() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
    )

    failed = await orchestrator.run(
        _control_workflow(),
        target_resource_id="scope-2",
        trigger_ts=_TRIGGER_TS,
        context={
            "signal.evidence.updated": "received",
            "requester.principal": "operator-a",
            "approval.board_approval.operator-a": "approved",
            "approval.board_approval.operator-b": "approved",
        },
    )
    completed = await orchestrator.run(
        _control_workflow(),
        target_resource_id="scope-3",
        trigger_ts=_TRIGGER_TS,
        context={
            "signal.evidence.updated": "received",
            "requester.principal": "operator-a",
            "approval.board_approval.operator-b": "approved",
            "approval.board_approval.operator-c": "approved",
            "decision.board_decision": "approved",
        },
    )

    assert failed.status is ProcessStatus.WAITING
    assert failed.step_results[-1].reason == "waiting_for_approval_quorum"
    assert completed.status is ProcessStatus.SUCCEEDED


async def test_wait_timeout_terminates_process() -> None:
    audit = InMemoryStateStore()
    orchestrator = _orchestrator(audit)
    timed_out = await orchestrator.run(
        _control_workflow(),
        target_resource_id="scope-timeout",
        trigger_ts=_TRIGGER_TS,
        context={"started_at.evidence": _TRIGGER_TS.isoformat()},
        now=_TRIGGER_TS + timedelta(seconds=121),
    )

    assert timed_out.status is ProcessStatus.TIMED_OUT
    assert next(item for item in timed_out.step_results if item.step_id == "evidence").reason == (
        "wait_timed_out"
    )


async def _approval_step_result(context: dict[str, str]) -> object:
    """Run one approval-gated step against a supplied approval context."""
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id="p-approval",
            workflow_ref="wf",
            workflow_version="1.0.0",
            status=ProcessStatus.RUNNING,
            current_step="gated_step",
            target_resource_id="res-1",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="corr-approval",
        ),
        event=ProcessEvent(
            event_id="event-create",
            process_id="p-approval",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="p-approval:create",
            recorded_at=_TRIGGER_TS,
            correlation_id="corr-approval",
        ),
    )
    executor = ShadowWorkflowStepExecutor(
        process_id="p-approval",
        action_types=_ACTION_TYPES,
        audit_store=audit,
        approvals={},
        process_store=process_store,
        snapshot=snapshot,
        context=context,
    )
    return await executor.execute(
        runbook_id="wf",
        step=RunbookStep(
            id="gated_step",
            action_type="ops.gated",
            kind=WorkflowStepKind.APPROVAL,
            quorum=2,
            no_self_approval=True,
        ),
    )


async def test_one_operator_cannot_satisfy_a_quorum_under_two_spellings() -> None:
    """Azure UPNs and object ids are case-insensitive, so counting raw keys let
    a single operator meet a two-approver quorum alone.
    """
    result = await _approval_step_result(
        {
            "requester.principal": "operator-z",
            "approval.gated_step.operator-a": "approved",
            "approval.gated_step.OPERATOR-A": "approved",
        }
    )

    assert result.outcome is RunbookStepOutcome.WAITING


async def test_a_recased_requester_does_not_approve_their_own_step() -> None:
    """no_self_approval compared raw strings, so the requester's own approval
    counted toward the quorum under a different case.
    """
    result = await _approval_step_result(
        {
            "requester.principal": "operator-a",
            "approval.gated_step.OPERATOR-A": "approved",
            "approval.gated_step.operator-b": "approved",
        }
    )

    assert result.outcome is RunbookStepOutcome.WAITING


async def test_two_distinct_operators_still_meet_the_quorum() -> None:
    result = await _approval_step_result(
        {
            "requester.principal": "operator-z",
            "approval.gated_step.operator-a": "approved",
            "approval.gated_step.operator-b": "approved",
        }
    )

    assert result.outcome is RunbookStepOutcome.SUCCESS
