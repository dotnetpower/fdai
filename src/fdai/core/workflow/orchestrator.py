"""Workflow orchestrator (shadow) - run a Workflow's steps through the
existing RunbookRunner, judge-and-log only, never mutating.

This is the P1 process orchestrator the action ontology reserved as
declared-but-not-yet-live (see docs/roadmap/decisioning/process-automation.md 4-5). It
closes the gap between a compiled Workflow and an audited run:

1. build the :class:`~fdai.core.workflow.approval.ApprovalPlan` (who approves
   each step, resolved from Entra RBAC + the notification matrix);
2. derive an idempotent :class:`Process` id from
   ``(workflow, target_resource_id, trigger_ts)``;
3. compile the Workflow to a :class:`~fdai.core.runbook.models.Runbook` and walk
   it with :class:`~fdai.core.runbook.runner.RunbookRunner`, using a
   **shadow** step executor that writes an audit entry per step and returns
   success without ever mutating a resource.

Shadow-only by construction
---------------------------

:class:`ShadowWorkflowStepExecutor` has no publisher, no direct-API executor,
and no resource lock - it structurally cannot mutate. A step is judged and
logged (with its resolved approval requirement) and reported ``SUCCESS``.
Promotion to a live (enforce) executor that re-enters the risk-gate ->
executor -> delivery path is a separate, gated change; until then a workflow
run cannot change cloud state. This mirrors the "new capabilities ship in
shadow" invariant in architecture.instructions.md.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome, RunbookStepResult
from fdai.core.runbook.runner import RunbookRunner
from fdai.core.workflow.approval import ApprovalPlan, StepApproval, WorkflowApprovalPlanner
from fdai.core.workflow.compiler import compile_workflow
from fdai.shared.contracts.models import OntologyActionType, Workflow, WorkflowStepKind
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore

_ACTOR = "fdai.core.workflow.orchestrator"

_PARAM_TOKEN = re.compile(r"\$\{([a-z0-9_.]+)\}")


def _resolve_params(params: Mapping[str, object], context: Mapping[str, str]) -> dict[str, object]:
    """Substitute ``${token}`` in string param values from ``context``.

    Only string values are templated; a token with no context entry is left
    verbatim so the unresolved reference is visible in the audit rather than
    silently blanked. Non-string values pass through unchanged.
    """
    resolved: dict[str, object] = {}
    for key, value in params.items():
        if isinstance(value, str):
            resolved[key] = _PARAM_TOKEN.sub(lambda m: context.get(m.group(1), m.group(0)), value)
        else:
            resolved[key] = value
    return resolved


@runtime_checkable
class WorkflowGuardEvaluator(Protocol):
    """Evaluate a step's ``guard_rule_ref`` at run time.

    A guard is the deterministic "when" for a step - a policy-as-code predicate,
    never model text. The upstream default injects no evaluator, so a guard is
    load-validated but recorded as ``not_evaluated`` at run time; a fork (or the
    enforce path) binds a concrete OPA-backed evaluator via this seam. The
    implementation MUST be deterministic and side-effect free.
    """

    async def evaluate(self, *, rule_id: str, step_id: str, process_id: str) -> bool:
        """Return True when the guard permits the step to proceed."""
        ...


_PROCESS_KEY_PREFIX = "process:"


def process_state_key(process_id: str) -> str:
    """State-store key holding the :class:`Process` record for ``process_id``."""
    return f"{_PROCESS_KEY_PREFIX}{process_id}"


def _process_record(
    *,
    process_id: str,
    workflow_name: str,
    status: ProcessStatus,
    current_step: str,
    target_resource_id: str,
    started_at: datetime,
) -> dict[str, object]:
    """Build a ``Process`` ObjectType row (process-automation.md 3.1)."""
    return {
        "id": process_id,
        "workflow_ref": workflow_name,
        "status": status.value,
        "current_step": current_step,
        "target_resource_id": target_resource_id,
        "started_at": started_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class ProcessRun:
    """The result of one shadow Workflow run."""

    process_id: str
    workflow_name: str
    status: ProcessStatus
    step_results: tuple[RunbookStepResult, ...]
    approval_plan: ApprovalPlan
    replayed: bool = False


class ShadowWorkflowStepExecutor:
    """A :class:`~fdai.core.runbook.runner.StepExecutor` that judges and logs a
    step without mutating. It has no path to a publisher or executor, so the
    shadow invariant is structural, not conventional."""

    __slots__ = (
        "_process_id",
        "_action_types",
        "_audit",
        "_approvals",
        "_guards",
        "_guard_evaluator",
        "_params",
        "_process_store",
        "_snapshot",
        "_context",
        "_now",
    )

    def __init__(
        self,
        *,
        process_id: str,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
        approvals: Mapping[str, StepApproval],
        guards: Mapping[str, str] | None = None,
        guard_evaluator: WorkflowGuardEvaluator | None = None,
        params: Mapping[str, Mapping[str, object]] | None = None,
        process_store: ProcessRuntimeStore,
        snapshot: ProcessSnapshot,
        context: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._process_id = process_id
        self._action_types = action_types
        self._audit = audit_store
        self._approvals = approvals
        self._guards = guards or {}
        self._guard_evaluator = guard_evaluator
        self._params = params or {}
        self._process_store = process_store
        self._snapshot = snapshot
        self._context = context or {}
        self._now = now or datetime.now(tz=UTC)

    async def execute(self, *, runbook_id: str, step: RunbookStep) -> RunbookStepResult:
        self._snapshot = await self._transition(
            kind=ProcessEventKind.STEP_STARTED,
            status=ProcessStatus.RUNNING,
            current_step=step.id,
            step_id=step.id,
            suffix="started",
        )
        approval = self._approvals.get(step.id)
        known = step.kind is not WorkflowStepKind.ACTION or step.action_type in self._action_types
        guard_ref = self._guards.get(step.id)

        guard_evaluated = False
        guard_passed: bool | None = None
        if guard_ref is not None and self._guard_evaluator is not None:
            guard_evaluated = True
            guard_passed = await self._guard_evaluator.evaluate(
                rule_id=guard_ref, step_id=step.id, process_id=self._process_id
            )

        await self._audit.append_audit_entry(
            {
                "event_id": _event_id(self._process_id, f"step:{step.id}:audit"),
                "correlation_id": self._snapshot.correlation_id,
                "actor": _ACTOR,
                "action_kind": "workflow.step",
                "mode": "shadow",
                "process_id": self._process_id,
                "workflow": runbook_id,
                "step_id": step.id,
                "action_type": step.action_type,
                "action_known": known,
                "requires_approval": approval.requires_approval if approval else False,
                "required_role": (
                    approval.required_role.value if approval and approval.required_role else None
                ),
                "approver_group": approval.entra_group_ref if approval else None,
                "notify_channels": list(approval.notify_channels) if approval else [],
                "guard_rule_ref": guard_ref,
                "guard_evaluated": guard_evaluated,
                "guard_passed": guard_passed,
                "params": dict(self._params.get(step.id, {})),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

        control_result = await self._control_result(
            step=step,
            guard_evaluated=guard_evaluated,
            guard_passed=guard_passed,
        )
        if control_result is not None:
            result = control_result
        elif not known:
            result = RunbookStepResult(
                step_id=step.id,
                action_type=step.action_type,
                outcome=RunbookStepOutcome.FAILURE,
                reason="unknown_action_type",
            )
        elif guard_evaluated and guard_passed is False:
            # The guard blocked the step. In shadow the action would not apply,
            # so this is a judged no-op, not a run failure - the run continues.
            result = RunbookStepResult(
                step_id=step.id,
                action_type=step.action_type,
                outcome=RunbookStepOutcome.SUCCESS,
                reason="guard_blocked_shadow_noop",
            )
        else:
            result = RunbookStepResult(
                step_id=step.id,
                action_type=step.action_type,
                outcome=RunbookStepOutcome.SUCCESS,
                reason="shadow_judge_and_log",
            )
        event_kind, process_status, suffix = self._result_transition(step, result)
        event_payload: dict[str, object] = {
            "outcome": result.outcome.value,
            "reason": result.reason,
            "step_kind": step.kind.value,
        }
        if step.kind is WorkflowStepKind.APPROVAL:
            event_payload.update(
                {
                    "decision": self._context.get(f"approval.{step.id}", "pending"),
                    "required_role": (
                        approval.required_role.value
                        if approval is not None and approval.required_role is not None
                        else "approver"
                    ),
                    "quorum": step.quorum,
                    "no_self_approval": step.no_self_approval,
                }
            )
        if step.kind is WorkflowStepKind.DECISION:
            event_payload["decision"] = self._context.get(f"decision.{step.id}", "unknown")
        self._snapshot = await self._transition(
            kind=event_kind,
            status=process_status,
            current_step=step.id,
            step_id=step.id,
            suffix=suffix,
            payload=event_payload,
        )
        return result

    async def _control_result(
        self,
        *,
        step: RunbookStep,
        guard_evaluated: bool,
        guard_passed: bool | None,
    ) -> RunbookStepResult | None:
        if step.kind is WorkflowStepKind.ACTION:
            return None
        if step.kind is WorkflowStepKind.PARALLEL:
            return await self._parallel_result(step)
        if step.kind is WorkflowStepKind.WAIT:
            if self._timed_out(step):
                return _step_result(step, RunbookStepOutcome.FAILURE, "wait_timed_out")
            satisfied = _truthy(self._context.get(f"signal.{step.wait_for}"))
            return _step_result(
                step,
                RunbookStepOutcome.SUCCESS if satisfied else RunbookStepOutcome.WAITING,
                "wait_signal_received" if satisfied else f"waiting_for:{step.wait_for}",
            )
        if step.kind is WorkflowStepKind.APPROVAL:
            if self._timed_out(step):
                return _step_result(step, RunbookStepOutcome.FAILURE, "approval_timed_out")
            decisions = _approval_decisions(self._context, step.id)
            if not decisions:
                return _step_result(step, RunbookStepOutcome.WAITING, "waiting_for_approval")
            requester = self._context.get("requester.principal")
            approved_by = {
                principal
                for principal, decision in decisions.items()
                if decision == "approved" and (not step.no_self_approval or principal != requester)
            }
            if len(approved_by) >= step.quorum:
                return _step_result(step, RunbookStepOutcome.SUCCESS, "approval_recorded")
            if any(decision == "rejected" for decision in decisions.values()):
                return _step_result(step, RunbookStepOutcome.FAILURE, "approval_rejected")
            return _step_result(step, RunbookStepOutcome.WAITING, "waiting_for_approval_quorum")
        if step.kind is WorkflowStepKind.DECISION:
            outcome = self._context.get(f"decision.{step.id}")
            if outcome is None:
                return _step_result(step, RunbookStepOutcome.WAITING, "waiting_for_decision")
            if outcome not in step.outcomes:
                return _step_result(step, RunbookStepOutcome.FAILURE, "invalid_decision_outcome")
            return _step_result(step, RunbookStepOutcome.SUCCESS, f"decision:{outcome}")
        if step.kind is WorkflowStepKind.GATE:
            if not guard_evaluated:
                return _step_result(step, RunbookStepOutcome.WAITING, "waiting_for_gate_evaluation")
            return _step_result(
                step,
                RunbookStepOutcome.SUCCESS if guard_passed else RunbookStepOutcome.FAILURE,
                "gate_passed" if guard_passed else "gate_blocked",
            )
        return _step_result(step, RunbookStepOutcome.FAILURE, "unsupported_step_kind")

    async def _parallel_result(self, step: RunbookStep) -> RunbookStepResult:
        async def run_branch(branch: str) -> bool:
            started = datetime.now(tz=UTC)
            await self._process_store.append_event(
                self._branch_event(
                    step=step,
                    branch=branch,
                    kind=ProcessEventKind.PARALLEL_BRANCH_STARTED,
                    suffix="started",
                    recorded_at=started,
                )
            )
            failed = self._context.get(f"parallel.{step.id}.{branch}", "success") == "failed"
            await self._process_store.append_event(
                self._branch_event(
                    step=step,
                    branch=branch,
                    kind=(
                        ProcessEventKind.PARALLEL_BRANCH_FAILED
                        if failed
                        else ProcessEventKind.PARALLEL_BRANCH_COMPLETED
                    ),
                    suffix="failed" if failed else "completed",
                    recorded_at=datetime.now(tz=UTC),
                )
            )
            return not failed

        outcomes = await asyncio.gather(*(run_branch(branch) for branch in step.branches))
        return _step_result(
            step,
            RunbookStepOutcome.SUCCESS if all(outcomes) else RunbookStepOutcome.FAILURE,
            "parallel_branches_completed" if all(outcomes) else "parallel_branch_failed",
        )

    def _branch_event(
        self,
        *,
        step: RunbookStep,
        branch: str,
        kind: ProcessEventKind,
        suffix: str,
        recorded_at: datetime,
    ) -> ProcessEvent:
        return ProcessEvent(
            event_id=_event_id(self._process_id, f"step:{step.id}:branch:{branch}:{suffix}"),
            process_id=self._process_id,
            kind=kind,
            idempotency_key=f"{self._process_id}:step:{step.id}:branch:{branch}:{suffix}",
            recorded_at=recorded_at,
            correlation_id=self._snapshot.correlation_id,
            step_id=step.id,
            payload={"branch": branch},
        )

    def _timed_out(self, step: RunbookStep) -> bool:
        if step.timeout_seconds is None:
            return False
        raw = self._context.get(f"started_at.{step.id}")
        if raw is None:
            return False
        try:
            started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        return (self._now - started).total_seconds() >= step.timeout_seconds

    @staticmethod
    def _result_transition(
        step: RunbookStep,
        result: RunbookStepResult,
    ) -> tuple[ProcessEventKind, ProcessStatus, str]:
        if result.outcome is RunbookStepOutcome.WAITING:
            if step.kind is WorkflowStepKind.APPROVAL:
                return ProcessEventKind.APPROVAL_REQUESTED, ProcessStatus.WAITING, "waiting"
            return ProcessEventKind.STEP_WAITING, ProcessStatus.WAITING, "waiting"
        if result.outcome is RunbookStepOutcome.FAILURE:
            if result.reason in {"wait_timed_out", "approval_timed_out"}:
                return ProcessEventKind.PROCESS_TIMED_OUT, ProcessStatus.TIMED_OUT, "timed-out"
            return ProcessEventKind.STEP_FAILED, ProcessStatus.RUNNING, "failed"
        if step.kind is WorkflowStepKind.APPROVAL:
            return ProcessEventKind.APPROVAL_RECORDED, ProcessStatus.RUNNING, "completed"
        if step.kind is WorkflowStepKind.DECISION:
            return ProcessEventKind.DECISION_RECORDED, ProcessStatus.RUNNING, "completed"
        if step.kind is WorkflowStepKind.WAIT:
            return ProcessEventKind.EVIDENCE_ATTACHED, ProcessStatus.RUNNING, "completed"
        return ProcessEventKind.STEP_COMPLETED, ProcessStatus.RUNNING, "completed"

    async def _transition(
        self,
        *,
        kind: ProcessEventKind,
        status: ProcessStatus,
        current_step: str,
        step_id: str,
        suffix: str,
        payload: Mapping[str, object] | None = None,
    ) -> ProcessSnapshot:
        recorded_at = datetime.now(tz=UTC)
        return await self._process_store.transition(
            process_id=self._process_id,
            expected_revision=self._snapshot.revision,
            status=status,
            current_step=current_step,
            event=ProcessEvent(
                event_id=_event_id(self._process_id, f"step:{step_id}:{suffix}"),
                process_id=self._process_id,
                kind=kind,
                idempotency_key=f"{self._process_id}:step:{step_id}:attempt:1:{suffix}",
                recorded_at=recorded_at,
                correlation_id=self._snapshot.correlation_id,
                step_id=step_id,
                payload=payload or {},
            ),
        )


def derive_process_id(*, workflow_name: str, target_resource_id: str, trigger_ts: datetime) -> str:
    """Idempotent Process id from ``(workflow, target, trigger_ts)``.

    A retried trigger with the same key reuses the id, so a re-delivery does not
    start a second Process (process-automation.md 3.1).
    """
    key = f"{workflow_name}:{target_resource_id}:{trigger_ts.isoformat()}"
    return str(uuid5(NAMESPACE_URL, key))


class WorkflowOrchestrator:
    """Run a Workflow in shadow: plan approvals, then walk the compiled Runbook
    with a non-mutating step executor, auditing the whole run."""

    __slots__ = ("_planner", "_action_types", "_audit", "_guard_evaluator", "_process_store")

    def __init__(
        self,
        *,
        planner: WorkflowApprovalPlanner,
        action_types: Mapping[str, OntologyActionType],
        audit_store: StateStore,
        process_store: ProcessRuntimeStore,
        guard_evaluator: WorkflowGuardEvaluator | None = None,
    ) -> None:
        self._planner = planner
        self._action_types = action_types
        self._audit = audit_store
        self._guard_evaluator = guard_evaluator
        self._process_store = process_store

    async def run(
        self,
        workflow: Workflow,
        *,
        target_resource_id: str,
        trigger_ts: datetime,
        context: Mapping[str, str] | None = None,
        correlation_id: str | None = None,
        now: datetime | None = None,
    ) -> ProcessRun:
        """Execute ``workflow`` in shadow over ``target_resource_id`` and return
        the :class:`ProcessRun`. Never mutates a resource.

        ``context`` supplies additional ``${token}`` values for step param
        substitution (e.g. ``event.event_type`` from the coordinator); the
        target resource and trigger timestamp are always available as
        ``event.resource_ref`` / ``event.trigger_ts``.
        """
        plan = self._planner.plan(workflow)
        approvals = {s.step_id: s for s in plan.steps}
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
            )
        subst_context: dict[str, str] = {
            "event.resource_ref": target_resource_id,
            "event.trigger_ts": trigger_ts.isoformat(),
        }
        if context:
            subst_context.update(context)
        resolved_params = {s.id: _resolve_params(s.params, subst_context) for s in workflow.steps}

        if created:
            await self._audit.append_audit_entry(
                {
                    "event_id": _event_id(process_id, "plan"),
                    "correlation_id": resolved_correlation_id,
                    "actor": _ACTOR,
                    "action_kind": "workflow.process-plan",
                    "mode": "shadow",
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
            audit_store=self._audit,
            approvals=approvals,
            guards=guards,
            guard_evaluator=self._guard_evaluator,
            params=resolved_params,
            process_store=self._process_store,
            snapshot=snapshot,
            context=context,
            now=now,
        )
        runner = RunbookRunner(executor=executor, audit_store=self._audit)
        result = await runner.run(
            compiled.runbook,
            start_step_id=start_step,
            audit_context={
                "event_id": _event_id(process_id, "terminal-audit"),
                "correlation_id": resolved_correlation_id,
                "process_id": process_id,
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
        )


def _event_id(process_id: str, suffix: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{process_id}:{suffix}"))


def _step_result(
    step: RunbookStep,
    outcome: RunbookStepOutcome,
    reason: str,
) -> RunbookStepResult:
    return RunbookStepResult(
        step_id=step.id,
        action_type=step.action_type,
        outcome=outcome,
        reason=reason,
    )


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "received"}


def _approval_decisions(context: Mapping[str, str], step_id: str) -> dict[str, str]:
    prefix = f"approval.{step_id}."
    decisions = {
        key.removeprefix(prefix): value.strip().lower()
        for key, value in context.items()
        if key.startswith(prefix) and key != f"{prefix}started_at"
    }
    legacy = context.get(f"approval.{step_id}")
    if legacy is not None:
        decisions.setdefault("legacy", legacy.strip().lower())
    return decisions


__all__ = [
    "ProcessRun",
    "ProcessStatus",
    "ShadowWorkflowStepExecutor",
    "WorkflowGuardEvaluator",
    "WorkflowOrchestrator",
    "derive_process_id",
]
