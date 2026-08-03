"""WorkflowOrchestrator (shadow) tests.

Covers the P1 shadow run: plan approvals, walk the compiled Runbook with a
non-mutating step executor, and audit the whole run. Proves the shadow
invariant (no mutation), the audit trail shape, idempotent Process ids, and
that a gated step carries its resolved approver assignment into the audit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.orchestrator import (
    ProcessStatus,
    ShadowWorkflowStepExecutor,
    WorkflowCancellationError,
    WorkflowOrchestrator,
    WorkflowRetryError,
    derive_process_id,
)
from fdai.core.workflow.workflow_resume import WorkflowResumeError
from fdai.core.workflow.workflow_runtime import WorkflowVerifiedOutcome
from fdai.delivery.persistence.state_store_hil_registry import (
    StateStoreHilApprovalRegistry,
)
from fdai.delivery.persistence.workflow_approval import (
    StateStoreWorkflowApprovalProvider,
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
from fdai.shared.providers.hil_registry import HilApprovalDecision
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


class _ResolvingOutcomeVerifier(_AcceptingOutcomeVerifier):
    async def resolve(self, **kwargs: str) -> WorkflowVerifiedOutcome:
        return WorkflowVerifiedOutcome(
            outcome="succeeded",
            receipt_ref=f"receipt:{kwargs['step_id']}",
        )


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
                params={
                    "resource_group": "example-rg",
                    "vm_name": "example-vm",
                    "reason": "Apply the planned example change.",
                },
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


async def test_enforce_action_steps_resume_from_durable_outcomes_without_context() -> None:
    audit = InMemoryStateStore()
    dispatcher = _RecordingActionDispatcher()
    verifier = _ResolvingOutcomeVerifier()
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        action_dispatcher=dispatcher,
        outcome_verifier=verifier,
    )
    context = {"requester.principal": "operator-1"}

    first = await orchestrator.run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context=context,
        mode=Mode.ENFORCE,
    )
    second = await orchestrator.run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context=context,
        mode=Mode.ENFORCE,
    )
    completed = await orchestrator.run(
        _workflow(),
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context=context,
        mode=Mode.ENFORCE,
    )

    assert first.status is ProcessStatus.WAITING
    assert second.status is ProcessStatus.WAITING
    assert completed.status is ProcessStatus.SUCCEEDED
    assert len(dispatcher.calls) == 2
    assert [call["receipt_ref"] for call in verifier.calls] == [
        "receipt:auto_step",
        "receipt:gated_step",
    ]


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


async def test_effect_free_failure_retries_with_distinct_attempt_identity() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    workflow = _workflow()
    initial = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
    )
    failed = await initial.run(
        workflow,
        target_resource_id="retry-target",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )
    dispatcher = _RecordingActionDispatcher()
    retrying = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        action_dispatcher=dispatcher,
        outcome_verifier=_ResolvingOutcomeVerifier(),
    )

    retried = await retrying.retry(
        process_id=failed.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
        now=_TRIGGER_TS + timedelta(seconds=30),
    )

    assert failed.status is ProcessStatus.FAILED
    assert retried.status is ProcessStatus.WAITING
    assert dispatcher.calls[0]["attempt"] == 2
    events = await process_store.events(failed.process_id)
    retry_event = next(
        event for event in events if event.kind is ProcessEventKind.PROCESS_RETRY_REQUESTED
    )
    dispatch_event = next(
        event
        for event in events
        if event.kind is ProcessEventKind.ACTION_DISPATCHED and event.attempt == 2
    )
    assert retry_event.attempt == 2
    assert dispatch_event.payload["proposal_ref"] == "proposal-1"
    assert ":attempt:2:" in dispatch_event.idempotency_key


async def test_retry_rejects_failed_attempt_with_dispatch_evidence() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    dispatcher = _RecordingActionDispatcher()
    workflow = _workflow()
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
    )
    waiting = await orchestrator.run(
        workflow,
        target_resource_id="retry-blocked-target",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )
    snapshot = await process_store.get(waiting.process_id)
    assert snapshot is not None
    await process_store.transition(
        process_id=waiting.process_id,
        expected_revision=snapshot.revision,
        status=ProcessStatus.FAILED,
        current_step="",
        event=ProcessEvent(
            event_id="retry-blocked-terminal",
            process_id=waiting.process_id,
            kind=ProcessEventKind.PROCESS_FAILED,
            idempotency_key=f"{waiting.process_id}:attempt:1:forced-terminal",
            recorded_at=_TRIGGER_TS + timedelta(seconds=10),
            correlation_id=snapshot.correlation_id,
            attempt=1,
            payload={"reason": "synthetic_terminal_failure"},
        ),
    )

    with pytest.raises(WorkflowRetryError, match="dispatch") as error:
        await orchestrator.retry(
            process_id=waiting.process_id,
            workflows={workflow.name: workflow},
            actor_oid="owner-1",
        )

    assert error.value.kind == "retry_requires_recovery"


async def test_retry_rejects_ambiguous_dispatch_failure_without_local_receipt() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    workflow = _workflow()
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        action_dispatcher=_FailingActionDispatcher(fail_step="auto_step"),
    )
    failed = await orchestrator.run(
        workflow,
        target_resource_id="retry-ambiguous-target",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )

    with pytest.raises(WorkflowRetryError, match="effect-free") as error:
        await orchestrator.retry(
            process_id=failed.process_id,
            workflows={workflow.name: workflow},
            actor_oid="owner-1",
        )

    assert failed.status is ProcessStatus.FAILED
    assert error.value.kind == "retry_requires_recovery"


async def test_retry_rejects_terminal_attempt_limit() -> None:
    process_store = InMemoryProcessRuntimeStore()
    workflow = _workflow()
    process_id = derive_process_id(
        workflow_name=workflow.name,
        target_resource_id="retry-limit-target",
        trigger_ts=_TRIGGER_TS,
    )
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=process_id,
            workflow_ref=workflow.name,
            workflow_version=str(workflow.version),
            status=ProcessStatus.FAILED,
            current_step="",
            target_resource_id="retry-limit-target",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="retry-limit-correlation",
        ),
        event=ProcessEvent(
            event_id="retry-limit-created",
            process_id=process_id,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="retry-limit-created-key",
            recorded_at=_TRIGGER_TS,
            correlation_id="retry-limit-correlation",
            payload={
                "resume": {
                    "trigger_ts": _TRIGGER_TS.isoformat(),
                    "mode": Mode.SHADOW.value,
                    "context": {},
                    "context_complete": True,
                }
            },
        ),
    )
    snapshot = await process_store.transition(
        process_id=process_id,
        expected_revision=snapshot.revision,
        status=ProcessStatus.RUNNING,
        current_step="auto_step",
        event=ProcessEvent(
            event_id="retry-limit-step-failed",
            process_id=process_id,
            kind=ProcessEventKind.STEP_FAILED,
            idempotency_key="retry-limit-step-failed-key",
            recorded_at=_TRIGGER_TS,
            correlation_id="retry-limit-correlation",
            step_id="auto_step",
            attempt=3,
        ),
    )
    await process_store.transition(
        process_id=process_id,
        expected_revision=snapshot.revision,
        status=ProcessStatus.FAILED,
        current_step="",
        event=ProcessEvent(
            event_id="retry-limit-terminal",
            process_id=process_id,
            kind=ProcessEventKind.PROCESS_FAILED,
            idempotency_key="retry-limit-terminal-key",
            recorded_at=_TRIGGER_TS,
            correlation_id="retry-limit-correlation",
            attempt=3,
        ),
    )
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=InMemoryStateStore(),
        process_store=process_store,
    )

    with pytest.raises(WorkflowRetryError, match="limit") as error:
        await orchestrator.retry(
            process_id=process_id,
            workflows={workflow.name: workflow},
            actor_oid="owner-1",
            max_attempts=3,
        )

    assert error.value.kind == "retry_attempt_limit"


async def test_enforce_action_rejects_sensitive_params_without_persisting_value() -> None:
    action_type = _ACTION_TYPES["remediate.auto"].model_copy(
        update={
            "argument_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "credential": {"type": "string", "x-fdai-redact": True},
                },
            }
        }
    )
    workflow = _workflow().model_copy(
        update={
            "steps": [
                WorkflowStep(
                    id="sensitive",
                    action_type_ref=action_type.name,
                    params={"credential": "${secret.value}"},
                )
            ]
        }
    )
    audit = InMemoryStateStore()
    dispatcher = _RecordingActionDispatcher()
    process_store = InMemoryProcessRuntimeStore()
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types={action_type.name: action_type},
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types={action_type.name: action_type},
        audit_store=audit,
        process_store=process_store,
        action_dispatcher=dispatcher,
    )

    run = await orchestrator.run(
        workflow,
        target_resource_id="res-1",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "secret.value": "sensitive-value",
        },
        mode=Mode.ENFORCE,
    )

    assert run.status is ProcessStatus.FAILED
    assert run.step_results[0].reason == "workflow_sensitive_params_unsupported"
    assert dispatcher.calls == []
    assert "sensitive-value" not in str(audit.audit_entries)
    created = (await process_store.events(run.process_id))[0]
    assert created.payload["resume"]["context_complete"] is False
    assert "sensitive-value" not in str(created.payload)
    with pytest.raises(WorkflowResumeError, match="redacted") as error:
        await orchestrator.resume(process_id=run.process_id, workflow=workflow)
    assert error.value.kind == "resume_context_redacted"
    step_audit = next(
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "workflow.step"
    )
    assert step_audit["params"] == {"credential": "[REDACTED]"}
    assert step_audit["params_redacted"] == ["credential"]


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
    assert dispatcher.calls[2]["params"] == {
        "resource_group": "example-rg",
        "vm_name": "example-vm",
        "reason": "Apply the planned example change.",
    }
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
    holds = StateStoreAutomationHoldLedger(audit)
    await holds.issue(
        target_ref="res-1",
        process_id=recovering.process_id,
        reason="prior_recovery_failure",
    )

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
    assert not await holds.is_held(target_ref="res-1")
    assert any(
        row["entry"]["action_kind"] == "workflow.automation_hold.released"
        for row in audit.audit_entries
    )


async def test_verified_compensation_cannot_release_another_process_hold() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    workflow = _compensated_workflow()
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
        outcome_verifier=_AcceptingOutcomeVerifier(),
    )
    await orchestrator.run(
        workflow,
        target_resource_id="res-held",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
    )
    compensating = await orchestrator.run(
        workflow,
        target_resource_id="res-held",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "action.apply_first.status": "verified",
            "action.apply_first.receipt_ref": "receipt:apply:1",
        },
        mode=Mode.ENFORCE,
    )
    holds = StateStoreAutomationHoldLedger(audit)
    await holds.issue(
        target_ref="res-held",
        process_id="another-process",
        reason="another_recovery_failure",
    )

    failed = await orchestrator.run(
        workflow,
        target_resource_id="res-held",
        trigger_ts=_TRIGGER_TS,
        context={
            "requester.principal": "operator-1",
            "compensation.apply_first.status": "verified",
            "compensation.apply_first.receipt_ref": "receipt:rollback:1",
        },
        mode=Mode.ENFORCE,
    )

    assert failed.process_id == compensating.process_id
    assert failed.status is ProcessStatus.FAILED
    assert await holds.is_held(target_ref="res-held")
    events = await process_store.events(failed.process_id)
    assert events[-1].payload["reason"] == "automation_hold_release_failed"
    assert events[-1].payload["recovery_incomplete"] is True


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
    assert await StateStoreAutomationHoldLedger(audit).is_held(target_ref="res-2")
    assert any(
        row["entry"]["action_kind"] == "workflow.automation_hold.issued"
        for row in audit.audit_entries
    )


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


async def test_action_step_attempt_is_recorded_in_dispatch_and_journal() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    dispatcher = _RecordingActionDispatcher()
    snapshot, _ = await process_store.create(
        snapshot=ProcessSnapshot(
            process_id="p-attempt",
            workflow_ref="wf",
            workflow_version="1.0.0",
            status=ProcessStatus.PENDING,
            current_step="",
            target_resource_id="res-1",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="corr-attempt",
        ),
        event=ProcessEvent(
            event_id="event-attempt-create",
            process_id="p-attempt",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="p-attempt:create",
            recorded_at=_TRIGGER_TS,
            correlation_id="corr-attempt",
        ),
    )
    executor = ShadowWorkflowStepExecutor(
        process_id="p-attempt",
        action_types=_ACTION_TYPES,
        action_dispatcher=dispatcher,
        audit_store=audit,
        approvals={},
        process_store=process_store,
        snapshot=snapshot,
        context={"requester.principal": "operator-1"},
        mode=Mode.ENFORCE,
        attempt=2,
    )

    result = await executor.execute(
        runbook_id="wf",
        step=RunbookStep(id="apply", action_type="remediate.auto"),
    )

    assert result.outcome is RunbookStepOutcome.WAITING
    assert dispatcher.calls[0]["attempt"] == 2
    events = (await process_store.events("p-attempt"))[1:]
    assert [event.kind for event in events] == [
        ProcessEventKind.STEP_STARTED,
        ProcessEventKind.ACTION_DISPATCHED,
        ProcessEventKind.STEP_WAITING,
    ]
    assert {event.attempt for event in events} == {2}
    assert all(":attempt:2:" in event.idempotency_key for event in events)


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


def _approval_workflow(*, name: str, timeout_seconds: int = 300) -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        trigger=WorkflowTrigger(
            kind=WorkflowTriggerKind.SIGNAL,
            signal_type="change.request.submitted",
        ),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="owner_approval",
                kind=WorkflowStepKind.APPROVAL,
                approval_role=CeilingRole.OWNER,
                quorum=2,
                no_self_approval=True,
                timeout_seconds=timeout_seconds,
            )
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


async def test_enforce_approval_uses_only_durable_var_receipts() -> None:
    audit = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(audit)
    registry = StateStoreHilApprovalRegistry(store=audit)
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
        approval_provider=provider,
    )
    workflow = _control_workflow()

    waiting = await orchestrator.run(
        workflow,
        target_resource_id="scope-durable-approval",
        trigger_ts=_TRIGGER_TS,
        context={
            "signal.evidence.updated": "received",
            "requester.principal": "requester-1",
            "approval.board_approval.forged-a": "approved",
            "approval.board_approval.forged-b": "approved",
        },
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )
    assert waiting.status is ProcessStatus.WAITING
    assert waiting.step_results[-1].reason == "waiting_for_approval"

    pending = await registry.list_pending()
    assert len(pending) == 2
    for item, approver in zip(pending, ("operator-a", "operator-b"), strict=True):
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=approver,
        )

    completed = await orchestrator.run(
        workflow,
        target_resource_id="scope-durable-approval",
        trigger_ts=_TRIGGER_TS,
        context={
            "signal.evidence.updated": "received",
            "requester.principal": "requester-1",
            "decision.board_decision": "approved",
        },
        now=_TRIGGER_TS + timedelta(seconds=30),
        mode=Mode.ENFORCE,
    )

    assert completed.status is ProcessStatus.SUCCEEDED
    events = await process_store.events(completed.process_id)
    recorded = next(event for event in events if event.kind is ProcessEventKind.APPROVAL_RECORDED)
    assert recorded.payload["decision"] == "approved"


async def test_enforce_approval_resumes_from_exact_process_id() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    provider = StateStoreWorkflowApprovalProvider(audit)
    registry = StateStoreHilApprovalRegistry(store=audit)
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        approval_provider=provider,
    )
    workflow = Workflow(
        schema_version="1.0.0",
        name="approval-only",
        version="1.0.0",
        trigger=WorkflowTrigger(
            kind=WorkflowTriggerKind.SIGNAL,
            signal_type="change.request.submitted",
        ),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="owner_approval",
                kind=WorkflowStepKind.APPROVAL,
                approval_role=CeilingRole.OWNER,
                quorum=2,
                no_self_approval=True,
                timeout_seconds=300,
            )
        ],
    )
    waiting = await orchestrator.run(
        workflow,
        target_resource_id="scope-resume",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "requester-1", "unused": "not-persisted"},
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )
    for item, approver in zip(
        await registry.list_pending(),
        ("owner-a", "owner-b"),
        strict=True,
    ):
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=approver,
        )

    resumed = await orchestrator.resume(
        process_id=waiting.process_id,
        workflow=workflow,
        now=_TRIGGER_TS + timedelta(seconds=30),
    )

    assert resumed.status is ProcessStatus.SUCCEEDED
    created = (await process_store.events(waiting.process_id))[0]
    assert created.payload["resume"]["context"] == {"requester.principal": "requester-1"}


async def test_waiting_approval_cancellation_closes_var_slots() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    provider = StateStoreWorkflowApprovalProvider(audit)
    registry = StateStoreHilApprovalRegistry(store=audit)
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        approval_provider=provider,
    )
    workflow = Workflow(
        schema_version="1.0.0",
        name="cancel-approval",
        version="1.0.0",
        trigger=WorkflowTrigger(
            kind=WorkflowTriggerKind.SIGNAL,
            signal_type="change.request.submitted",
        ),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="owner_approval",
                kind=WorkflowStepKind.APPROVAL,
                approval_role=CeilingRole.OWNER,
                quorum=2,
                no_self_approval=True,
                timeout_seconds=300,
            )
        ],
    )
    waiting = await orchestrator.run(
        workflow,
        target_resource_id="scope-cancel",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "requester-1"},
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )
    assert waiting.status is ProcessStatus.WAITING
    assert len(await registry.list_pending()) == 2

    cancelled = await orchestrator.cancel(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
        now=_TRIGGER_TS + timedelta(seconds=30),
    )

    assert cancelled.status is ProcessStatus.CANCELLED
    assert await registry.list_pending() == ()
    events = await process_store.events(waiting.process_id)
    assert [event.kind for event in events[-2:]] == [
        ProcessEventKind.PROCESS_CANCELLATION_REQUESTED,
        ProcessEventKind.PROCESS_CANCELLED,
    ]

    replayed = await orchestrator.cancel(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
        now=_TRIGGER_TS + timedelta(seconds=40),
    )
    assert replayed.status is ProcessStatus.CANCELLED
    assert [
        event.kind
        for event in await process_store.events(waiting.process_id)
        if event.kind is ProcessEventKind.PROCESS_CANCELLED
    ] == [ProcessEventKind.PROCESS_CANCELLED]


async def test_rejected_approval_retries_with_fresh_attempt_slots() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    provider = StateStoreWorkflowApprovalProvider(audit)
    registry = StateStoreHilApprovalRegistry(store=audit)
    workflow = _approval_workflow(name="approval-rerequest")
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        approval_provider=provider,
    )
    waiting = await orchestrator.run(
        workflow,
        target_resource_id="approval-rerequest-target",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "requester-1"},
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )
    first_slot = (await registry.list_pending())[0]
    await registry.record_decision(
        idempotency_key=first_slot.idempotency_key,
        decision=HilApprovalDecision.REJECT,
        approver_oid="owner-a",
    )
    rejected = await orchestrator.resume(
        process_id=waiting.process_id,
        workflow=workflow,
        now=_TRIGGER_TS + timedelta(seconds=10),
    )

    retried = await orchestrator.retry(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-retry",
        now=_TRIGGER_TS + timedelta(seconds=20),
    )
    second_slots = await registry.list_pending()

    assert rejected.status is ProcessStatus.FAILED
    assert retried.status is ProcessStatus.WAITING
    assert len(second_slots) == 2
    assert all(item.metadata["attempt"] == "2" for item in second_slots)
    assert all(item.approval_id != first_slot.approval_id for item in second_slots)

    for item, approver in zip(second_slots, ("owner-b", "owner-c"), strict=True):
        await registry.record_decision(
            idempotency_key=item.idempotency_key,
            decision=HilApprovalDecision.APPROVE,
            approver_oid=approver,
        )
    completed = await orchestrator.retry(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-retry",
        now=_TRIGGER_TS + timedelta(seconds=30),
    )
    assert completed.status is ProcessStatus.SUCCEEDED


async def test_timed_out_approval_retries_with_fresh_attempt_slots() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    provider = StateStoreWorkflowApprovalProvider(audit)
    registry = StateStoreHilApprovalRegistry(store=audit)
    workflow = _approval_workflow(name="approval-timeout-rerequest", timeout_seconds=10)
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=process_store,
        approval_provider=provider,
    )
    waiting = await orchestrator.run(
        workflow,
        target_resource_id="approval-timeout-target",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "requester-1"},
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )
    timed_out = await orchestrator.resume(
        process_id=waiting.process_id,
        workflow=workflow,
        now=_TRIGGER_TS + timedelta(seconds=11),
    )

    retried = await orchestrator.retry(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-retry",
        now=_TRIGGER_TS + timedelta(seconds=12),
    )
    pending = await registry.list_pending()

    assert timed_out.status is ProcessStatus.TIMED_OUT
    assert retried.status is ProcessStatus.WAITING
    assert len(pending) == 2
    assert all(item.metadata["attempt"] == "2" for item in pending)

    cancelled = await orchestrator.cancel(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-retry",
        now=_TRIGGER_TS + timedelta(seconds=13),
    )
    assert cancelled.status is ProcessStatus.CANCELLED
    assert await registry.list_pending() == ()


async def test_waiting_action_cancellation_reconciles_then_compensates() -> None:
    audit = InMemoryStateStore()
    process_store = InMemoryProcessRuntimeStore()
    dispatcher = _RecordingActionDispatcher()
    verifier = _ResolvingOutcomeVerifier()
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
    workflow = _compensated_workflow()
    waiting = await orchestrator.run(
        workflow,
        target_resource_id="scope-cancel-action",
        trigger_ts=_TRIGGER_TS,
        context={"requester.principal": "requester-1"},
        mode=Mode.ENFORCE,
    )
    assert waiting.status is ProcessStatus.WAITING

    cancelling = await orchestrator.cancel(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
        now=_TRIGGER_TS + timedelta(seconds=30),
    )

    assert cancelling.status is ProcessStatus.COMPENSATING
    assert [call["step"].id for call in dispatcher.calls] == [
        "apply_first",
        "compensate_apply_first",
    ]
    events = await process_store.events(waiting.process_id)
    assert not any(
        event.kind is ProcessEventKind.ACTION_DISPATCHED and event.step_id == "apply_second"
        for event in events
    )

    compensated = await orchestrator.cancel(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
        now=_TRIGGER_TS + timedelta(seconds=40),
    )
    replayed = await orchestrator.cancel(
        process_id=waiting.process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
        now=_TRIGGER_TS + timedelta(seconds=50),
    )

    assert compensated.status is ProcessStatus.COMPENSATED
    assert replayed.status is ProcessStatus.COMPENSATED
    assert [call["step"].id for call in dispatcher.calls] == [
        "apply_first",
        "compensate_apply_first",
    ]


async def test_running_process_cancellation_requires_safe_boundary() -> None:
    process_store = InMemoryProcessRuntimeStore()
    workflow = _workflow()
    process_id = derive_process_id(
        workflow_name=workflow.name,
        target_resource_id="scope-running",
        trigger_ts=_TRIGGER_TS,
    )
    await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=process_id,
            workflow_ref=workflow.name,
            workflow_version=str(workflow.version),
            status=ProcessStatus.RUNNING,
            current_step="auto_step",
            target_resource_id="scope-running",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="correlation-running",
        ),
        event=ProcessEvent(
            event_id="running-created-event",
            process_id=process_id,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="running-created-key",
            recorded_at=_TRIGGER_TS,
            correlation_id="correlation-running",
            payload={
                "resume": {
                    "trigger_ts": _TRIGGER_TS.isoformat(),
                    "mode": Mode.ENFORCE.value,
                    "context": {"requester.principal": "requester-1"},
                    "context_complete": True,
                }
            },
        ),
    )
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=InMemoryStateStore(),
        process_store=process_store,
    )

    with pytest.raises(WorkflowCancellationError, match="safe boundary") as error:
        await orchestrator.cancel(
            process_id=process_id,
            workflows={workflow.name: workflow},
            actor_oid="owner-1",
        )

    assert error.value.kind == "process_not_at_safe_boundary"


async def test_pending_process_cancels_before_approval_state_exists() -> None:
    process_store = InMemoryProcessRuntimeStore()
    workflow = _control_workflow()
    process_id = derive_process_id(
        workflow_name=workflow.name,
        target_resource_id="scope-pending",
        trigger_ts=_TRIGGER_TS,
    )
    await process_store.create(
        snapshot=ProcessSnapshot(
            process_id=process_id,
            workflow_ref=workflow.name,
            workflow_version=str(workflow.version),
            status=ProcessStatus.PENDING,
            current_step="",
            target_resource_id="scope-pending",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="correlation-pending",
        ),
        event=ProcessEvent(
            event_id="pending-created-event",
            process_id=process_id,
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="pending-created-key",
            recorded_at=_TRIGGER_TS,
            correlation_id="correlation-pending",
            payload={
                "resume": {
                    "trigger_ts": _TRIGGER_TS.isoformat(),
                    "mode": Mode.ENFORCE.value,
                    "context": {"requester.principal": "requester-1"},
                    "context_complete": True,
                }
            },
        ),
    )
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=InMemoryStateStore(),
        process_store=process_store,
        approval_provider=StateStoreWorkflowApprovalProvider(InMemoryStateStore()),
    )

    cancelled = await orchestrator.cancel(
        process_id=process_id,
        workflows={workflow.name: workflow},
        actor_oid="owner-1",
    )

    assert cancelled.status is ProcessStatus.CANCELLED


async def test_resume_rejects_workflow_version_drift() -> None:
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
    workflow = _workflow()
    run = await orchestrator.run(
        workflow,
        target_resource_id="scope-version-drift",
        trigger_ts=_TRIGGER_TS,
    )
    changed = Workflow.model_validate({**workflow.model_dump(mode="json"), "version": "2.0.0"})

    with pytest.raises(WorkflowResumeError, match="catalog version") as error:
        await orchestrator.resume(process_id=run.process_id, workflow=changed)

    assert error.value.kind == "workflow_version_mismatch"


async def test_resume_rejects_process_identity_mismatch() -> None:
    process_store = InMemoryProcessRuntimeStore()
    workflow = _workflow()
    await process_store.create(
        snapshot=ProcessSnapshot(
            process_id="forged-process-id",
            workflow_ref=workflow.name,
            workflow_version=str(workflow.version),
            status=ProcessStatus.WAITING,
            current_step="auto_step",
            target_resource_id="scope-identity",
            started_at=_TRIGGER_TS,
            updated_at=_TRIGGER_TS,
            correlation_id="correlation-identity",
        ),
        event=ProcessEvent(
            event_id="forged-created-event",
            process_id="forged-process-id",
            kind=ProcessEventKind.PROCESS_CREATED,
            idempotency_key="forged-created-key",
            recorded_at=_TRIGGER_TS,
            correlation_id="correlation-identity",
            payload={
                "resume": {
                    "trigger_ts": _TRIGGER_TS.isoformat(),
                    "mode": Mode.SHADOW.value,
                    "context": {},
                    "context_complete": True,
                }
            },
        ),
    )
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=InMemoryStateStore(),
        process_store=process_store,
    )

    with pytest.raises(WorkflowResumeError, match="does not match") as error:
        await orchestrator.resume(process_id="forged-process-id", workflow=workflow)

    assert error.value.kind == "process_identity_mismatch"


async def test_enforce_approval_timeout_uses_persisted_request_clock() -> None:
    audit = InMemoryStateStore()
    provider = StateStoreWorkflowApprovalProvider(audit)
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        approval_provider=provider,
    )
    workflow = _control_workflow()
    base_context = {
        "signal.evidence.updated": "received",
        "requester.principal": "requester-1",
    }
    await orchestrator.run(
        workflow,
        target_resource_id="scope-durable-timeout",
        trigger_ts=_TRIGGER_TS,
        context=base_context,
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )

    timed_out = await orchestrator.run(
        workflow,
        target_resource_id="scope-durable-timeout",
        trigger_ts=_TRIGGER_TS,
        context={
            **base_context,
            "started_at.board_approval": (_TRIGGER_TS + timedelta(seconds=120)).isoformat(),
            "approval.board_approval.forged-a": "approved",
            "approval.board_approval.forged-b": "approved",
        },
        now=_TRIGGER_TS + timedelta(seconds=121),
        mode=Mode.ENFORCE,
    )

    assert timed_out.status is ProcessStatus.TIMED_OUT
    assert (
        next(
            result for result in timed_out.step_results if result.step_id == "board_approval"
        ).reason
        == "approval_timed_out"
    )


async def test_enforce_approval_timeout_persistence_failure_is_explicit() -> None:
    audit = InMemoryStateStore()

    class FailingTimeoutProvider(StateStoreWorkflowApprovalProvider):
        async def mark_timed_out(self, **kwargs: object) -> bool:
            del kwargs
            raise RuntimeError("synthetic timeout persistence failure")

    provider = FailingTimeoutProvider(audit)
    orchestrator = WorkflowOrchestrator(
        planner=WorkflowApprovalPlanner(
            action_types=_ACTION_TYPES,
            group_mapping=_group_mapping(),
            matrix=_matrix(),
        ),
        action_types=_ACTION_TYPES,
        audit_store=audit,
        process_store=InMemoryProcessRuntimeStore(),
        approval_provider=provider,
    )
    workflow = _control_workflow()
    context = {
        "signal.evidence.updated": "received",
        "requester.principal": "requester-1",
    }
    await orchestrator.run(
        workflow,
        target_resource_id="scope-timeout-persistence-failure",
        trigger_ts=_TRIGGER_TS,
        context=context,
        now=_TRIGGER_TS,
        mode=Mode.ENFORCE,
    )

    failed = await orchestrator.run(
        workflow,
        target_resource_id="scope-timeout-persistence-failure",
        trigger_ts=_TRIGGER_TS,
        context=context,
        now=_TRIGGER_TS + timedelta(seconds=121),
        mode=Mode.ENFORCE,
    )

    assert (
        next(result for result in failed.step_results if result.step_id == "board_approval").reason
        == "approval_evidence_unavailable"
    )


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
