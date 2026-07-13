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
    run = await orchestrator.run(
        _workflow(), target_resource_id="res-1", trigger_ts=_TRIGGER_TS
    )
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
