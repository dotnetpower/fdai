"""Non-mutating workflow step execution with guards and process events."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.core.runbook.models import RunbookStep, RunbookStepOutcome, RunbookStepResult
from fdai.core.workflow.approval import StepApproval
from fdai.core.workflow.workflow_runtime import (
    ACTOR,
    WorkflowActionDispatcher,
    WorkflowContextualGuardEvaluator,
    WorkflowEvidenceDispatcher,
    WorkflowGuardEvaluator,
    WorkflowOutcomeResolver,
    WorkflowOutcomeVerifier,
    approval_decisions,
    event_id,
    step_result,
    truthy,
)
from fdai.rule_catalog.schema.action_type import argument_schema_redaction_paths
from fdai.shared.contracts.models import Mode, OntologyActionType, WorkflowStepKind
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore


def _normalized_principal(value: object) -> str:
    """Canonical form of a principal identifier for identity comparison.

    Azure UPNs and object ids are case-insensitive, so two spellings name one
    operator. Comparing raw strings would let that operator count twice toward
    a quorum, or approve a step they requested.
    """

    return str(value or "").strip().casefold()


class ShadowWorkflowStepExecutor:
    """Judge and log workflow steps without exposing a mutation path."""

    __slots__ = (
        "_process_id",
        "_action_types",
        "_action_dispatcher",
        "_evidence_dispatcher",
        "_audit",
        "_approvals",
        "_guards",
        "_guard_evaluator",
        "_outcome_verifier",
        "_params",
        "_process_store",
        "_snapshot",
        "_context",
        "_now",
        "_mode",
        "_target_resource_id",
    )

    def __init__(
        self,
        *,
        process_id: str,
        action_types: Mapping[str, OntologyActionType],
        action_dispatcher: WorkflowActionDispatcher | None = None,
        evidence_dispatcher: WorkflowEvidenceDispatcher | None = None,
        audit_store: StateStore,
        approvals: Mapping[str, StepApproval],
        guards: Mapping[str, str] | None = None,
        guard_evaluator: (WorkflowGuardEvaluator | WorkflowContextualGuardEvaluator | None) = None,
        outcome_verifier: WorkflowOutcomeVerifier | None = None,
        params: Mapping[str, Mapping[str, object]] | None = None,
        process_store: ProcessRuntimeStore,
        snapshot: ProcessSnapshot,
        context: Mapping[str, str] | None = None,
        now: datetime | None = None,
        mode: Mode = Mode.SHADOW,
        target_resource_id: str = "",
    ) -> None:
        self._process_id = process_id
        self._action_types = action_types
        self._action_dispatcher = action_dispatcher
        self._evidence_dispatcher = evidence_dispatcher
        self._audit = audit_store
        self._approvals = approvals
        self._guards = guards or {}
        self._guard_evaluator = guard_evaluator
        self._outcome_verifier = outcome_verifier
        self._params = params or {}
        self._process_store = process_store
        self._snapshot = snapshot
        self._context = context or {}
        self._now = now or datetime.now(tz=UTC)
        self._mode = mode
        self._target_resource_id = target_resource_id or snapshot.target_resource_id

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
        step_params = dict(self._params.get(step.id, {}))
        redacted_params, redacted_paths = self._redacted_params(step, step_params)

        guard_evaluated = False
        guard_passed: bool | None = None
        if guard_ref is not None and self._guard_evaluator is not None:
            guard_evaluated = True
            if isinstance(self._guard_evaluator, WorkflowContextualGuardEvaluator):
                guard_passed = await self._guard_evaluator.evaluate_context(
                    rule_id=guard_ref,
                    step_id=step.id,
                    process_id=self._process_id,
                    target_resource_id=self._target_resource_id,
                    at=self._now,
                )
            else:
                guard_passed = await self._guard_evaluator.evaluate(
                    rule_id=guard_ref,
                    step_id=step.id,
                    process_id=self._process_id,
                )

        await self._audit.append_audit_entry(
            {
                "event_id": event_id(self._process_id, f"step:{step.id}:audit"),
                "correlation_id": self._snapshot.correlation_id,
                "actor": ACTOR,
                "action_kind": "workflow.step",
                "mode": self._mode.value,
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
                "params": redacted_params,
                "params_redacted": sorted(redacted_paths),
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
            result = step_result(step, RunbookStepOutcome.FAILURE, "unknown_action_type")
        elif guard_evaluated and guard_passed is False:
            result = step_result(
                step,
                (
                    RunbookStepOutcome.SUCCESS
                    if self._mode is Mode.SHADOW
                    else RunbookStepOutcome.FAILURE
                ),
                (
                    "guard_blocked_shadow_noop"
                    if self._mode is Mode.SHADOW
                    else "guard_blocked_enforce"
                ),
            )
        elif step.kind is WorkflowStepKind.ACTION and self._mode is Mode.ENFORCE:
            if redacted_paths:
                result = step_result(
                    step,
                    RunbookStepOutcome.FAILURE,
                    "workflow_sensitive_params_unsupported",
                )
            else:
                result = await self._dispatch_action(step)
        else:
            result = step_result(step, RunbookStepOutcome.SUCCESS, "shadow_judge_and_log")

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

    def _redacted_params(
        self,
        step: RunbookStep,
        params: Mapping[str, object],
    ) -> tuple[dict[str, object], frozenset[str]]:
        action_type = self._action_types.get(step.action_type)
        if action_type is None:
            return dict(params), frozenset()
        configured = argument_schema_redaction_paths(action_type)
        present = frozenset(path for path in configured if path in params)
        return {
            key: "[REDACTED]" if key in present else value for key, value in params.items()
        }, present

    async def _dispatch_action(self, step: RunbookStep) -> RunbookStepResult:
        events = await self._process_store.events(self._process_id)
        dispatch_event = next(
            (
                event
                for event in events
                if event.kind is ProcessEventKind.ACTION_DISPATCHED and event.step_id == step.id
            ),
            None,
        )
        if dispatch_event is not None:
            proposal_ref = str(dispatch_event.payload.get("proposal_ref") or "").strip()
            if not proposal_ref or self._outcome_verifier is None:
                return step_result(
                    step,
                    RunbookStepOutcome.WAITING,
                    "waiting_for_action_outcome_verifier",
                )
            status = self._context.get(f"action.{step.id}.status")
            receipt_ref = self._context.get(f"action.{step.id}.receipt_ref", "").strip()
            outcome = "succeeded" if status == "verified" else "failed"
            try:
                if isinstance(self._outcome_verifier, WorkflowOutcomeResolver):
                    resolved = await self._outcome_verifier.resolve(
                        process_id=self._process_id,
                        step_id=step.id,
                        proposal_ref=proposal_ref,
                    )
                    if resolved is None:
                        return step_result(
                            step,
                            RunbookStepOutcome.WAITING,
                            "waiting_for_action_outcome",
                        )
                    outcome = resolved.outcome
                    receipt_ref = resolved.receipt_ref
                elif status not in {"verified", "failed"} or not receipt_ref:
                    return step_result(
                        step,
                        RunbookStepOutcome.WAITING,
                        "waiting_for_action_outcome",
                    )
                accepted = await self._outcome_verifier.verify(
                    process_id=self._process_id,
                    step_id=step.id,
                    proposal_ref=proposal_ref,
                    outcome=outcome,
                    receipt_ref=receipt_ref,
                )
            except Exception:  # noqa: BLE001 - verifier outage holds the Process
                accepted = False
            if not accepted:
                return step_result(
                    step,
                    RunbookStepOutcome.WAITING,
                    "waiting_for_action_outcome_verifier",
                )
            if outcome == "failed":
                return step_result(step, RunbookStepOutcome.FAILURE, "action_failed")
            if outcome == "succeeded":
                return step_result(step, RunbookStepOutcome.SUCCESS, "action_effect_verified")
            return step_result(step, RunbookStepOutcome.WAITING, "waiting_for_action_outcome")
        if self._action_dispatcher is None:
            return step_result(
                step,
                RunbookStepOutcome.FAILURE,
                "enforce_action_dispatcher_not_configured",
            )
        try:
            proposal_ref = await self._action_dispatcher.dispatch(
                process_id=self._process_id,
                correlation_id=self._snapshot.correlation_id,
                step=step,
                target_resource_id=self._target_resource_id,
                params=self._params.get(step.id, {}),
                context=self._context,
            )
        except Exception as exc:  # noqa: BLE001 - dispatcher boundary fails closed
            return step_result(
                step,
                RunbookStepOutcome.FAILURE,
                f"action_dispatch_failed:{type(exc).__name__}",
            )
        if not proposal_ref.strip():
            return step_result(
                step,
                RunbookStepOutcome.FAILURE,
                "action_dispatch_returned_no_reference",
            )
        await self._process_store.append_event(
            ProcessEvent(
                event_id=event_id(self._process_id, f"step:{step.id}:action-dispatched"),
                process_id=self._process_id,
                kind=ProcessEventKind.ACTION_DISPATCHED,
                idempotency_key=f"{self._process_id}:step:{step.id}:action-dispatched",
                recorded_at=datetime.now(tz=UTC),
                correlation_id=self._snapshot.correlation_id,
                step_id=step.id,
                payload={
                    "proposal_ref": proposal_ref,
                    "action_type": step.action_type,
                    "params": dict(self._params.get(step.id, {})),
                },
            )
        )
        return step_result(step, RunbookStepOutcome.WAITING, "waiting_for_action_outcome")

    async def _control_result(
        self,
        *,
        step: RunbookStep,
        guard_evaluated: bool,
        guard_passed: bool | None,
    ) -> RunbookStepResult | None:
        if step.kind is WorkflowStepKind.ACTION:
            return None
        if step.kind is WorkflowStepKind.EVIDENCE:
            return await self._dispatch_evidence(step)
        if step.kind is WorkflowStepKind.PARALLEL:
            return await self._parallel_result(step)
        if step.kind is WorkflowStepKind.WAIT:
            if self._timed_out(step):
                return step_result(step, RunbookStepOutcome.FAILURE, "wait_timed_out")
            satisfied = truthy(self._context.get(f"signal.{step.wait_for}"))
            return step_result(
                step,
                RunbookStepOutcome.SUCCESS if satisfied else RunbookStepOutcome.WAITING,
                "wait_signal_received" if satisfied else f"waiting_for:{step.wait_for}",
            )
        if step.kind is WorkflowStepKind.APPROVAL:
            if self._timed_out(step):
                return step_result(step, RunbookStepOutcome.FAILURE, "approval_timed_out")
            decisions = approval_decisions(self._context, step.id)
            if not decisions:
                return step_result(step, RunbookStepOutcome.WAITING, "waiting_for_approval")
            # Normalised before counting. Azure UPNs and object ids are
            # case-insensitive, so raw keys let the same operator satisfy a
            # quorum twice under two spellings, and let a requester's own
            # approval count despite no_self_approval.
            requester = _normalized_principal(self._context.get("requester.principal"))
            approved_by = {
                approver
                for approver in (
                    _normalized_principal(principal)
                    for principal, decision in decisions.items()
                    if decision == "approved"
                )
                if approver and not (step.no_self_approval and approver == requester)
            }
            if len(approved_by) >= step.quorum:
                return step_result(step, RunbookStepOutcome.SUCCESS, "approval_recorded")
            if any(decision == "rejected" for decision in decisions.values()):
                return step_result(step, RunbookStepOutcome.FAILURE, "approval_rejected")
            return step_result(step, RunbookStepOutcome.WAITING, "waiting_for_approval_quorum")
        if step.kind is WorkflowStepKind.DECISION:
            outcome = self._context.get(f"decision.{step.id}")
            if outcome is None:
                return step_result(step, RunbookStepOutcome.WAITING, "waiting_for_decision")
            if outcome not in step.outcomes:
                return step_result(step, RunbookStepOutcome.FAILURE, "invalid_decision_outcome")
            return step_result(step, RunbookStepOutcome.SUCCESS, f"decision:{outcome}")
        if step.kind is WorkflowStepKind.GATE:
            if not guard_evaluated:
                return step_result(step, RunbookStepOutcome.WAITING, "waiting_for_gate_evaluation")
            return step_result(
                step,
                RunbookStepOutcome.SUCCESS if guard_passed else RunbookStepOutcome.FAILURE,
                "gate_passed" if guard_passed else "gate_blocked",
            )
        return step_result(step, RunbookStepOutcome.FAILURE, "unsupported_step_kind")

    async def _dispatch_evidence(self, step: RunbookStep) -> RunbookStepResult:
        if self._evidence_dispatcher is None:
            return step_result(
                step,
                RunbookStepOutcome.FAILURE,
                "evidence_dispatcher_not_configured",
            )
        try:
            receipt = await self._evidence_dispatcher.dispatch(
                process_id=self._process_id,
                correlation_id=self._snapshot.correlation_id,
                step=step,
                params=self._params.get(step.id, {}),
            )
        except Exception as exc:  # noqa: BLE001 - evidence boundary fails closed
            return step_result(
                step,
                RunbookStepOutcome.FAILURE,
                f"evidence_capture_failed:{type(exc).__name__}",
            )
        if receipt.status != "captured":
            return step_result(
                step,
                RunbookStepOutcome.FAILURE,
                f"evidence_{receipt.status}:{receipt.reason or 'unknown'}",
            )
        return step_result(step, RunbookStepOutcome.SUCCESS, "browser_evidence_captured")

    async def _parallel_result(self, step: RunbookStep) -> RunbookStepResult:
        async def run_branch(branch: str) -> bool:
            await self._process_store.append_event(
                self._branch_event(
                    step=step,
                    branch=branch,
                    kind=ProcessEventKind.PARALLEL_BRANCH_STARTED,
                    suffix="started",
                    recorded_at=datetime.now(tz=UTC),
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
        return step_result(
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
            event_id=event_id(self._process_id, f"step:{step.id}:branch:{branch}:{suffix}"),
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
                event_id=event_id(self._process_id, f"step:{step_id}:{suffix}"),
                process_id=self._process_id,
                kind=kind,
                idempotency_key=f"{self._process_id}:step:{step_id}:attempt:1:{suffix}",
                recorded_at=recorded_at,
                correlation_id=self._snapshot.correlation_id,
                step_id=step_id,
                payload=payload or {},
            ),
        )
