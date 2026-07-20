"""Shadow workflow lifecycle orchestration.

The facade plans approvals, creates or resumes process state, compiles the
workflow, and delegates non-mutating step execution. Runtime helpers and the
step executor remain re-exported here for compatibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.core.runbook.models import RunbookStepOutcome
from fdai.core.runbook.runner import RunbookRunner
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.compiler import compile_workflow
from fdai.core.workflow.workflow_runtime import (
    ACTOR as _ACTOR,
)
from fdai.core.workflow.workflow_runtime import (
    ProcessRun,
    WorkflowActionDispatcher,
    WorkflowEvidenceDispatcher,
    WorkflowGuardEvaluator,
    derive_process_id,
    process_state_key,  # noqa: F401 - compatibility import
)
from fdai.core.workflow.workflow_runtime import (
    approval_decisions as _approval_decisions,  # noqa: F401 - compatibility import
)
from fdai.core.workflow.workflow_runtime import (
    event_id as _event_id,
)
from fdai.core.workflow.workflow_runtime import (
    process_record as _process_record,  # noqa: F401 - compatibility import
)
from fdai.core.workflow.workflow_runtime import (
    resolve_params as _resolve_params,
)
from fdai.core.workflow.workflow_runtime import (
    step_result as _step_result,  # noqa: F401 - compatibility import
)
from fdai.core.workflow.workflow_runtime import (
    truthy as _truthy,  # noqa: F401 - compatibility import
)
from fdai.core.workflow.workflow_step_executor import ShadowWorkflowStepExecutor
from fdai.shared.contracts.models import Mode, OntologyActionType, Workflow
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore


class WorkflowOrchestrator:
    """Plan and run a workflow through the non-mutating shadow executor."""

    __slots__ = (
        "_planner",
        "_action_types",
        "_action_dispatcher",
        "_evidence_dispatcher",
        "_audit",
        "_guard_evaluator",
        "_process_store",
    )

    def __init__(
        self,
        *,
        planner: WorkflowApprovalPlanner,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
        process_store: ProcessRuntimeStore,
        guard_evaluator: WorkflowGuardEvaluator | None = None,
        action_dispatcher: WorkflowActionDispatcher | None = None,
        evidence_dispatcher: WorkflowEvidenceDispatcher | None = None,
    ) -> None:
        self._planner = planner
        self._action_types = action_types
        self._action_dispatcher = action_dispatcher
        self._evidence_dispatcher = evidence_dispatcher
        self._audit = audit_store
        self._guard_evaluator = guard_evaluator
        self._process_store = process_store

    def with_action_dispatcher(
        self,
        dispatcher: WorkflowActionDispatcher,
    ) -> WorkflowOrchestrator:
        """Return an equivalent orchestrator with typed action republish enabled."""
        return WorkflowOrchestrator(
            planner=self._planner,
            action_types=self._action_types,
            audit_store=self._audit,
            process_store=self._process_store,
            guard_evaluator=self._guard_evaluator,
            action_dispatcher=dispatcher,
            evidence_dispatcher=self._evidence_dispatcher,
        )

    def with_evidence_dispatcher(
        self,
        dispatcher: WorkflowEvidenceDispatcher,
    ) -> WorkflowOrchestrator:
        """Return an equivalent orchestrator with evidence capture enabled."""
        return WorkflowOrchestrator(
            planner=self._planner,
            action_types=self._action_types,
            audit_store=self._audit,
            process_store=self._process_store,
            guard_evaluator=self._guard_evaluator,
            action_dispatcher=self._action_dispatcher,
            evidence_dispatcher=dispatcher,
        )

    async def run(
        self,
        workflow: Workflow,
        *,
        target_resource_id: str,
        trigger_ts: datetime,
        context: Mapping[str, str] | None = None,
        correlation_id: str | None = None,
        now: datetime | None = None,
        mode: Mode = Mode.SHADOW,
    ) -> ProcessRun:
        """Run a workflow in the requested mode through governed step dispatch."""
        plan = self._planner.plan(workflow)
        approvals = {step.step_id: step for step in plan.steps}
        process_id = derive_process_id(
            workflow_name=workflow.name,
            target_resource_id=target_resource_id,
            trigger_ts=trigger_ts,
        )
        started_at = datetime.now(tz=UTC)
        first_step = workflow.steps[0].id
        resolved_correlation_id = correlation_id or process_id
        snapshot, created = await self._process_store.create(
            snapshot=ProcessSnapshot(
                process_id=process_id,
                workflow_ref=workflow.name,
                workflow_version=str(workflow.version),
                status=ProcessStatus.PENDING,
                current_step="",
                target_resource_id=target_resource_id,
                started_at=started_at,
                updated_at=started_at,
                correlation_id=resolved_correlation_id,
            ),
            event=ProcessEvent(
                event_id=_event_id(process_id, "created"),
                process_id=process_id,
                kind=ProcessEventKind.PROCESS_CREATED,
                idempotency_key=f"{process_id}:created",
                recorded_at=started_at,
                correlation_id=resolved_correlation_id,
                payload={"workflow_ref": workflow.name, "workflow_version": str(workflow.version)},
            ),
        )
        if not created and snapshot.status.terminal:
            return ProcessRun(
                process_id=process_id,
                workflow_name=workflow.name,
                status=snapshot.status,
                step_results=(),
                approval_plan=plan,
                replayed=True,
                mode=mode.value,
            )

        subst_context: dict[str, str] = {
            "event.resource_ref": target_resource_id,
            "event.trigger_ts": trigger_ts.isoformat(),
        }
        if context:
            subst_context.update(context)
        resolved_params = {
            step.id: _resolve_params(step.params, subst_context) for step in workflow.steps
        }

        if created:
            await self._audit.append_audit_entry(
                {
                    "event_id": _event_id(process_id, "plan"),
                    "correlation_id": resolved_correlation_id,
                    "actor": _ACTOR,
                    "action_kind": "workflow.process-plan",
                    "mode": mode.value,
                    "declared_mode": workflow.default_mode.value,
                    "process_id": process_id,
                    "workflow": workflow.name,
                    "target_resource_id": target_resource_id,
                    "trigger_ts": trigger_ts.isoformat(),
                    "plan": plan.to_audit_dict(),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )

        start_step = snapshot.current_step or first_step
        snapshot = await self._process_store.transition(
            process_id=process_id,
            expected_revision=snapshot.revision,
            status=ProcessStatus.RUNNING,
            current_step=start_step,
            event=ProcessEvent(
                event_id=_event_id(process_id, "started"),
                process_id=process_id,
                kind=ProcessEventKind.PROCESS_STARTED,
                idempotency_key=f"{process_id}:started",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=resolved_correlation_id,
                step_id=start_step,
            ),
        )

        compiled = compile_workflow(workflow)
        guards: dict[str, str] = {}
        for workflow_step in workflow.steps:
            gate_or_rule = workflow_step.gate_ref or workflow_step.guard_rule_ref
            if gate_or_rule is not None:
                guards[workflow_step.id] = gate_or_rule
        executor = ShadowWorkflowStepExecutor(
            process_id=process_id,
            action_types=self._action_types,
            action_dispatcher=self._action_dispatcher,
            evidence_dispatcher=self._evidence_dispatcher,
            audit_store=self._audit,
            approvals=approvals,
            guards=guards,
            guard_evaluator=self._guard_evaluator,
            params=resolved_params,
            process_store=self._process_store,
            snapshot=snapshot,
            context=context,
            now=now,
            mode=mode,
            target_resource_id=target_resource_id,
        )
        runner = RunbookRunner(executor=executor, audit_store=self._audit)
        result = await runner.run(
            compiled.runbook,
            start_step_id=start_step,
            audit_context={
                "event_id": _event_id(process_id, "terminal-audit"),
                "correlation_id": resolved_correlation_id,
                "process_id": process_id,
                "mode": mode.value,
            },
        )

        if result.terminal_outcome is RunbookStepOutcome.WAITING:
            waiting = await self._process_store.get(process_id)
            if waiting is None:  # pragma: no cover - store invariant
                raise RuntimeError(f"process {process_id!r} vanished while waiting")
            return ProcessRun(
                process_id=process_id,
                workflow_name=workflow.name,
                status=ProcessStatus.WAITING,
                step_results=result.step_results,
                approval_plan=plan,
                replayed=not created,
                mode=mode.value,
            )

        current = await self._process_store.get(process_id)
        if current is None:  # pragma: no cover - store invariant
            raise RuntimeError(f"process {process_id!r} vanished before terminal transition")
        status = (
            ProcessStatus.SUCCEEDED
            if result.terminal_outcome is RunbookStepOutcome.SUCCESS
            else ProcessStatus.TIMED_OUT
            if current.status is ProcessStatus.TIMED_OUT
            else ProcessStatus.FAILED
        )
        if status is ProcessStatus.TIMED_OUT:
            return ProcessRun(
                process_id=process_id,
                workflow_name=workflow.name,
                status=status,
                step_results=result.step_results,
                approval_plan=plan,
                replayed=not created,
                mode=mode.value,
            )

        terminal_kind = (
            ProcessEventKind.PROCESS_COMPLETED
            if status is ProcessStatus.SUCCEEDED
            else ProcessEventKind.PROCESS_FAILED
        )
        await self._process_store.transition(
            process_id=process_id,
            expected_revision=current.revision,
            status=status,
            current_step="",
            event=ProcessEvent(
                event_id=_event_id(process_id, "terminal"),
                process_id=process_id,
                kind=terminal_kind,
                idempotency_key=f"{process_id}:terminal",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=resolved_correlation_id,
                payload={"terminal_outcome": result.terminal_outcome.value},
            ),
        )
        return ProcessRun(
            process_id=process_id,
            workflow_name=workflow.name,
            status=status,
            step_results=result.step_results,
            approval_plan=plan,
            replayed=not created,
            mode=mode.value,
        )


__all__ = [
    "ProcessRun",
    "ProcessStatus",
    "ShadowWorkflowStepExecutor",
    "WorkflowGuardEvaluator",
    "WorkflowOrchestrator",
    "derive_process_id",
    "process_state_key",
]
