"""HIL approval round-trip coordinator - park, push, resume.

Closes the gap between the risk gate returning ``hil`` and an approved
action actually running. The control loop never blocks on a human: it
uses the **park & return** model.

.. code-block:: text

    risk-gate -> hil
      -> HilResumeCoordinator.request_approval(action, rule, ...)
           1. park the full Action (+ context) in the StateStore under an
              opaque approval_id, status=pending
           2. push an A1 Adaptive Card via the HilChannel
           3. write a ``hil.requested`` audit entry
      -> ControlLoop.process(...) returns HIL (no blocking)

    ... later, a decision arrives (Teams/Slack callback or a poll) ...

    HilResumeCoordinator.resolve(approval_id, decision, approver_oid)
      - APPROVE -> restore the parked Action and re-dispatch to the executor
      - REJECT  -> record the reason, no execution
      - TIMEOUT -> no execution (fail-closed)
      - idempotent: a second resolve on a consumed park is a no-op

Safety invariants preserved
---------------------------

- **No auto-execute on HIL.** Nothing runs until :meth:`resolve` sees an
  ``APPROVE``; a missing / expired / consumed park never executes.
- **No self-approval.** ``approver_oid == submitter_oid`` is refused
  before any execution (the parked ``submitter_oid`` is the authority).
- **Idempotent.** The park's ``status`` flips to ``resolved`` on the
  first terminal decision; re-delivery of the same decision is a no-op,
  a conflicting decision is refused - re-execution can never happen.
- **Audit on every path.** request, approve+execute, reject, timeout,
  self-approval refusal, and unknown-park all append exactly one audit
  entry.

The coordinator lives in ``core/`` because it is a safety-critical
assembly point. It imports only Protocols from ``fdai.shared.providers``
and the core executor - never a concrete ChatOps / state adapter.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from fdai.core.executor import (
    DirectApiExecutionPort,
    MutationDependencyReadiness,
    ShadowExecutor,
    ThorExecutionPort,
)
from fdai.core.executor.safeguard_lifecycle_coordinator import (
    SafeguardLifecycleCoordinator,
)
from fdai.core.executor.tool_call import (
    ToolCallShadowExecutor,
)
from fdai.core.hil_resume.approval_records import (
    approval_expired as _approval_expired,
)
from fdai.core.hil_resume.approval_records import (
    park_key as _park_key,
)
from fdai.core.hil_resume.audit import HilAuditMixin
from fdai.core.hil_resume.delegation import (
    DelegationMode,
    DelegationRefusal,
    evaluate_hil_delegation,
)
from fdai.core.hil_resume.dispatch import HilDispatchMixin
from fdai.core.hil_resume.escalation_supervisor import (
    EscalationRung,
    HumanNonResponseSupervisor,
)
from fdai.core.hil_resume.integrity import is_execution_no_effect as _is_no_effect
from fdai.core.hil_resume.integrity import is_execution_pending as _is_pending
from fdai.core.hil_resume.integrity import is_execution_success as _is_success
from fdai.core.hil_resume.integrity import (
    parked_action_integrity_matches as _parked_action_integrity_matches,
)
from fdai.core.hil_resume.load_control import (
    ApprovalExpiryReconciler,
    ApprovalLoadController,
    ApprovalReminderDispatcher,
)
from fdai.core.hil_resume.reconciliation import produce_effect_reconciliation_request
from fdai.core.hil_resume.report_line import ReportLineHilCoordinator
from fdai.core.hil_resume.request import HilRequestMixin
from fdai.core.hil_resume.results import (
    RequestApprovalResult,
    RequestOutcome,
    ResolveOutcome,
    ResolveResult,
)
from fdai.core.hil_resume.rule_source import resolve_parked_rule
from fdai.core.human_reporting import (
    ApprovalContactConsentService,
    ReportLineApprovalRouter,
)
from fdai.core.oncall import OnCallResolver
from fdai.core.ontology_platform.evidence_conflict import EvidenceConflictCurrentReader
from fdai.core.ontology_platform.reconciliation_producer import EffectReconciliationRequestSink
from fdai.core.operational_planning import PreDispatchKineticSafetyWriter
from fdai.shared.contracts.models import (
    Action,
    OntologyActionType,
    Rule,
)
from fdai.shared.providers.hil_channel import (
    HilChannel,
    HilDecision,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

_STATUS_PENDING = "pending"
_STATUS_RESOLVED = "resolved"


class HilResumeCoordinator(HilAuditMixin, HilDispatchMixin, HilRequestMixin):
    """Parks HIL-routed actions and resumes them on an approval decision."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        executor: ShadowExecutor,
        hil_channel: HilChannel | None,
        rules_by_id: Mapping[str, Rule],
        direct_api_executor: DirectApiExecutionPort | None = None,
        tool_executor: ToolCallShadowExecutor | None = None,
        action_types_by_name: Mapping[str, OntologyActionType] | None = None,
        actor: str = "fdai.core.hil_resume",
        on_call_resolver: OnCallResolver | None = None,
        on_call_rotation: str | None = None,
        pending_index_writer: Callable[[StateStore, str], Awaitable[None]] | None = None,
        approval_load_controller: ApprovalLoadController | None = None,
        approval_expiry_reconciler: ApprovalExpiryReconciler | None = None,
        approval_reminder_dispatcher: ApprovalReminderDispatcher | None = None,
        escalation_supervisor: HumanNonResponseSupervisor | None = None,
        default_escalation_rungs: Sequence[EscalationRung] = (),
        pre_dispatch_kinetic_safety_writer: PreDispatchKineticSafetyWriter | None = None,
        thor_execution_port: ThorExecutionPort | None = None,
        mutation_dependency_readiness: MutationDependencyReadiness | None = None,
        evidence_conflict_reader: EvidenceConflictCurrentReader | None = None,
        safeguard_lifecycle_coordinator: SafeguardLifecycleCoordinator | None = None,
        effect_reconciliation_request_sink: EffectReconciliationRequestSink | None = None,
        report_line_router: ReportLineApprovalRouter | None = None,
        contact_consent_service: ApprovalContactConsentService | None = None,
    ) -> None:
        if (report_line_router is None) != (contact_consent_service is None):
            raise ValueError(
                "report_line_router and contact_consent_service MUST be bound together"
            )
        if report_line_router is not None and escalation_supervisor is None:
            raise ValueError("report-line routing requires an escalation supervisor")
        if (thor_execution_port is None) != (mutation_dependency_readiness is None):
            raise ValueError(
                "thor_execution_port and mutation_dependency_readiness MUST be bound together"
            )
        if thor_execution_port is not None:
            port_executor = cast(ShadowExecutor, thor_execution_port.pr_native)
            port_direct_api = thor_execution_port.direct_api
            port_tool = cast(
                ToolCallShadowExecutor | None,
                thor_execution_port.tool_call,
            )
            if (
                executor is not port_executor
                or direct_api_executor is not port_direct_api
                or tool_executor is not port_tool
            ):
                raise ValueError("HIL executor bindings MUST come from thor_execution_port")
        self._state_store = state_store
        self._thor_execution_port = thor_execution_port
        self._mutation_dependency_readiness = mutation_dependency_readiness
        self._executor = executor
        self._hil_channel = hil_channel
        self._rules_by_id = dict(rules_by_id)
        self._direct_api_executor = direct_api_executor
        self._tool_executor = tool_executor
        self._action_types_by_name = (
            dict(action_types_by_name) if action_types_by_name is not None else {}
        )
        self._actor = actor
        self._request_clock = lambda: datetime.now(tz=UTC)
        self._on_call_resolver = on_call_resolver
        self._on_call_rotation = on_call_rotation
        self._pending_index_writer = pending_index_writer
        self._approval_load_controller = approval_load_controller
        self.expiry_reconciler = approval_expiry_reconciler
        self.reminder_dispatcher = approval_reminder_dispatcher
        self.escalation_supervisor = escalation_supervisor
        self._default_escalation_rungs = tuple(default_escalation_rungs)
        self._pre_dispatch_kinetic_safety_writer = pre_dispatch_kinetic_safety_writer
        self._evidence_conflict_reader = evidence_conflict_reader
        self._safeguard_lifecycle_coordinator = safeguard_lifecycle_coordinator
        self._effect_reconciliation_request_sink = effect_reconciliation_request_sink
        self._report_line_hil = (
            ReportLineHilCoordinator(
                store=state_store,
                router=report_line_router,
                consent=contact_consent_service,
                escalation=escalation_supervisor,
                channel=hil_channel,
                load_controller=approval_load_controller,
                action_types=self._action_types_by_name,
                rules=self._rules_by_id,
                audit=self._audit,
                mark_resolved=self._mark_resolved,
                race_result=self._race_result,
                logger=_LOGGER,
            )
            if report_line_router is not None
            and contact_consent_service is not None
            and escalation_supervisor is not None
            else None
        )

    # ------------------------------------------------------------------
    # resolve (approve -> execute | reject | timeout)
    # ------------------------------------------------------------------

    async def resolve(
        self,
        *,
        approval_id: str,
        decision: HilDecision,
        approver_oid: str,
        reason: str = "",
        approver_can_approve_hil: bool = True,
    ) -> ResolveResult:
        """Apply a terminal decision to a parked action.

        Fail-safe: an unknown / already-resolved / self-approved park
        never executes. Only an ``APPROVE`` on a still-pending park
        re-dispatches the action to the executor.

        ``approver_can_approve_hil`` is the caller's RBAC verdict for
        ``Capability.APPROVE_RUNTIME_HIL`` (the Operator API HIL callback fills it
        from the operator's roles). The delegation gate refuses an approver
        who lacks it, and - when the park carries a different ``assignee_oid``
        than the approver - records the approval as **delegated** so the audit
        shows both the actual approver and the original assignee.
        """
        parked = await self._state_store.read_state(_park_key(approval_id))
        if parked is None:
            _LOGGER.warning("hil_resolve_unknown_park", extra={"approval_id": approval_id})
            await self._audit(
                action_kind="hil.resolve.not_found",
                idempotency_key=f"{approval_id}:hil_resolve_not_found",
                approval_id=approval_id,
                correlation_id=approval_id,
                detail={"decision": decision.value},
            )
            return ResolveResult(outcome=ResolveOutcome.NOT_FOUND, approval_id=approval_id)

        correlation_id = str(parked.get("correlation_id") or approval_id)
        idem = str(parked.get("idempotency_key") or approval_id)
        assignee_oid = str(parked.get("assignee_oid") or "").strip() or None

        if parked.get("status") == "awaiting_contact_consent":
            if self._report_line_hil is not None and self._report_line_hil.contact_consent_expired(
                parked,
                at=datetime.now(tz=UTC),
            ):
                claimed = await self._mark_resolved(
                    parked,
                    decision=HilDecision.TIMEOUT,
                    approver_oid="system:contact-consent-expiry",
                    action_kind="hil.report_line.contact_consent_expired",
                    detail={"attempted_decision": decision.value},
                )
                if not claimed:
                    return await self._race_result(approval_id, attempted=decision)
                return ResolveResult(
                    outcome=ResolveOutcome.TIMED_OUT,
                    approval_id=approval_id,
                    reason="contact_consent_expired",
                    assignee_oid=assignee_oid,
                )
            await self._audit(
                action_kind="hil.resolve.contact_consent_required",
                idempotency_key=f"{idem}:contact_consent_required",
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail={"attempted_decision": decision.value},
            )
            return ResolveResult(
                outcome=ResolveOutcome.CONTACT_CONSENT_REQUIRED,
                approval_id=approval_id,
                reason="report-line approval request has not been sent",
                assignee_oid=assignee_oid,
            )

        metadata = parked.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("decision_route") == "human_access":
            await self._audit(
                action_kind="hil.resolve.owned_route_held",
                idempotency_key=f"{idem}:owned_route_held",
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail={"decision_route": "human_access"},
            )
            return ResolveResult(
                outcome=ResolveOutcome.OWNED_ROUTE_HELD,
                approval_id=approval_id,
                reason="human access approval requires the Var-owned exact-material quorum",
            )

        if parked.get("status") == _STATUS_RESOLVED:
            prior = str(parked.get("decision") or "")
            if prior == HilDecision.TIMEOUT.value:
                return ResolveResult(
                    outcome=ResolveOutcome.TIMED_OUT,
                    approval_id=approval_id,
                    reason="approval_expired",
                )
            if prior and prior != decision.value:
                await self._audit(
                    action_kind="hil.resolve.conflict",
                    idempotency_key=f"{idem}:hil_resolve_conflict",
                    approval_id=approval_id,
                    correlation_id=correlation_id,
                    detail={"prior_decision": prior, "attempted": decision.value},
                )
                return ResolveResult(
                    outcome=ResolveOutcome.CONFLICTING_DECISION,
                    approval_id=approval_id,
                    reason=f"already resolved as {prior}",
                )
            return ResolveResult(outcome=ResolveOutcome.ALREADY_RESOLVED, approval_id=approval_id)

        if not _parked_action_integrity_matches(parked):
            claimed = await self._mark_resolved(
                parked,
                decision=HilDecision.TIMEOUT,
                approver_oid=approver_oid,
                action_kind="hil.resolve.integrity_failed",
                detail={"attempted_decision": decision.value},
            )
            if not claimed:
                return await self._race_result(approval_id, attempted=decision)
            return ResolveResult(
                outcome=ResolveOutcome.TIMED_OUT,
                approval_id=approval_id,
                reason="approval_integrity_failed",
            )

        if decision is HilDecision.APPROVE and _approval_expired(parked, now=datetime.now(tz=UTC)):
            claimed = await self._mark_resolved(
                parked,
                decision=HilDecision.TIMEOUT,
                approver_oid=approver_oid,
                action_kind="hil.timeout",
                detail={"reason": "approval_expired", "attempted_decision": decision.value},
            )
            if not claimed:
                return await self._race_result(approval_id, attempted=decision)
            return ResolveResult(
                outcome=ResolveOutcome.TIMED_OUT,
                approval_id=approval_id,
                reason="approval_expired",
            )

        submitter_oid = str(parked.get("submitter_oid") or "").strip()
        delegation = None
        if decision is HilDecision.APPROVE:
            action = Action.model_validate(parked["action"])
            if (
                isinstance(parked.get("report_line_route"), Mapping)
                and self._report_line_hil is None
            ):
                claimed = await self._mark_resolved(
                    parked=parked,
                    decision=HilDecision.TIMEOUT,
                    approver_oid=approver_oid,
                    action_kind="hil.report_line.route_unavailable",
                    detail={"attempted_decision": decision.value},
                )
                if not claimed:
                    return await self._race_result(approval_id, attempted=decision)
                return ResolveResult(
                    outcome=ResolveOutcome.TIMED_OUT,
                    approval_id=approval_id,
                    reason="report_line_route_unavailable",
                    assignee_oid=assignee_oid,
                )
            route_rejection = (
                await self._report_line_hil.guard_approval(
                    parked=parked,
                    action=action,
                    approval_id=approval_id,
                    approver_oid=approver_oid,
                )
                if self._report_line_hil is not None
                else None
            )
            if route_rejection is not None:
                return route_rejection
            # Delegation gate: no self-approval, a verifiable+distinct approver,
            # and the HIL-approval capability. Fail closed on any refusal. A
            # single pure function shared with the Operator API callback so the
            # rule never drifts between entry points.
            delegation = evaluate_hil_delegation(
                approver_oid=approver_oid,
                submitter_oid=submitter_oid,
                approver_can_approve_hil=approver_can_approve_hil,
                assignee_oid=assignee_oid,
            )
            if not delegation.allowed:
                if delegation.refusal is DelegationRefusal.MISSING_CAPABILITY:
                    await self._audit(
                        action_kind="hil.resolve.capability_refused",
                        idempotency_key=f"{idem}:hil_capability_refused",
                        approval_id=approval_id,
                        correlation_id=correlation_id,
                        detail={
                            "approver_oid": approver_oid,
                            "assignee_oid": assignee_oid,
                            "reason": DelegationRefusal.MISSING_CAPABILITY.value,
                        },
                    )
                    return ResolveResult(
                        outcome=ResolveOutcome.MISSING_CAPABILITY,
                        approval_id=approval_id,
                        assignee_oid=assignee_oid,
                    )
                await self._audit(
                    action_kind="hil.resolve.self_approval_refused",
                    idempotency_key=f"{idem}:hil_self_approval",
                    approval_id=approval_id,
                    correlation_id=correlation_id,
                    detail={
                        "approver_oid": approver_oid,
                        "reason": (
                            delegation.refusal.value
                            if delegation.refusal is not None
                            else "self_approval"
                        ),
                    },
                )
                return ResolveResult(
                    outcome=ResolveOutcome.SELF_APPROVAL_REFUSED, approval_id=approval_id
                )

        if decision is HilDecision.REJECT:
            claimed = await self._mark_resolved(
                parked,
                decision=decision,
                approver_oid=approver_oid,
                action_kind="hil.rejected",
                detail={"approver_oid": approver_oid, "reason": reason},
            )
            if not claimed:
                return await self._race_result(approval_id, attempted=decision)
            return ResolveResult(
                outcome=ResolveOutcome.REJECTED, approval_id=approval_id, reason=reason
            )

        if decision is HilDecision.TIMEOUT:
            claimed = await self._mark_resolved(
                parked,
                decision=decision,
                approver_oid=approver_oid,
                action_kind="hil.timeout",
                detail={},
            )
            if not claimed:
                return await self._race_result(approval_id, attempted=decision)
            return ResolveResult(outcome=ResolveOutcome.TIMED_OUT, approval_id=approval_id)

        # decision is APPROVE and the delegation gate allowed it -> re-dispatch.
        is_delegated = delegation is not None and delegation.is_delegated
        action = Action.model_validate(parked["action"])
        rule = self._resolve_rule(parked, action=action)
        # Mark resolved BEFORE executing so a concurrent duplicate decision
        # cannot double-apply; the executor is itself idempotent by
        # idempotency_key, this is defense in depth.
        claimed = await self._mark_resolved(
            parked,
            decision=decision,
            approver_oid=approver_oid,
            action_kind="hil.approved.claimed",
            detail={
                "approver_oid": approver_oid,
                **_report_line_audit_detail(parked),
            },
        )
        if not claimed:
            return await self._race_result(approval_id, attempted=decision)
        if rule is None:
            _LOGGER.error(
                "hil_resolve_rule_missing",
                extra={"approval_id": approval_id, "rule_id": parked.get("rule_id")},
            )
            await self._audit(
                action_kind="hil.approved.execute_failed",
                idempotency_key=f"{idem}:hil_execute_failed",
                approval_id=approval_id,
                correlation_id=correlation_id,
                detail={
                    "action_id": str(action.action_id),
                    "workflow_action": (
                        action.workflow_action.model_dump(mode="json")
                        if action.workflow_action is not None
                        else None
                    ),
                    "reason": "rule_not_in_catalog",
                    **_report_line_audit_detail(parked),
                },
            )
            return ResolveResult(
                outcome=ResolveOutcome.EXECUTE_FAILED,
                approval_id=approval_id,
                reason="rule_not_in_catalog",
                delegated=is_delegated,
                assignee_oid=assignee_oid,
            )

        result = await self._dispatch(
            action=action,
            rule=rule,
            correlation_id=correlation_id,
        )
        reconciliation = await produce_effect_reconciliation_request(
            self._effect_reconciliation_request_sink,
            action=action,
            result=result,
            correlation_id=correlation_id,
        )
        succeeded = _is_success(result)
        pending = _is_pending(result)
        no_effect = _is_no_effect(result)
        delegation_mode = (
            delegation.mode.value
            if delegation is not None and delegation.mode is not None
            else DelegationMode.ROLE_SCOPED.value
        )
        await self._audit(
            action_kind=(
                "hil.approved.executed"
                if succeeded
                else "hil.approved.execution_pending"
                if pending
                else "hil.approved.execution_not_attempted"
                if no_effect
                else "hil.approved.execute_failed"
            ),
            idempotency_key=f"{idem}:hil_executed",
            approval_id=approval_id,
            correlation_id=correlation_id,
            detail={
                "approver_oid": approver_oid,
                "assignee_oid": assignee_oid,
                "delegated": is_delegated,
                "delegation_mode": delegation_mode,
                "action_id": str(action.action_id),
                "action_type": action.action_type,
                "workflow_action": (
                    action.workflow_action.model_dump(mode="json")
                    if action.workflow_action is not None
                    else None
                ),
                "mode": action.mode.value,
                "execution_outcome": result.outcome.value,
                "safeguard_bundle_digest": result.safeguard_bundle_digest,
                **_report_line_audit_detail(parked),
                **(
                    {
                        "effect_reconciliation_request_status": reconciliation.status.value,
                        "effect_reconciliation_request_reason": reconciliation.reason_code,
                        "effect_reconciliation_id": reconciliation.reconciliation_id,
                    }
                    if reconciliation is not None
                    else {}
                ),
            },
        )
        return ResolveResult(
            outcome=(
                ResolveOutcome.EXECUTED
                if succeeded
                else ResolveOutcome.EXECUTION_PENDING
                if pending
                else ResolveOutcome.EXECUTION_NOT_ATTEMPTED
                if no_effect
                else ResolveOutcome.EXECUTE_FAILED
            ),
            approval_id=approval_id,
            execution_result=result,
            delegated=is_delegated,
            assignee_oid=assignee_oid,
        )

    def _resolve_rule(self, parked: Mapping[str, object], *, action: Action) -> Rule | None:
        return resolve_parked_rule(parked, action=action, rules_by_id=self._rules_by_id)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _race_result(
        self,
        approval_id: str,
        *,
        attempted: HilDecision,
    ) -> ResolveResult:
        latest = await self._state_store.read_state(_park_key(approval_id))
        prior = str(latest.get("decision") or "") if latest is not None else ""
        if prior == HilDecision.TIMEOUT.value:
            return ResolveResult(
                outcome=ResolveOutcome.TIMED_OUT,
                approval_id=approval_id,
                reason="approval_expired",
            )
        if prior and prior != attempted.value:
            return ResolveResult(
                outcome=ResolveOutcome.CONFLICTING_DECISION,
                approval_id=approval_id,
                reason=f"already resolved as {prior}",
            )
        return ResolveResult(outcome=ResolveOutcome.ALREADY_RESOLVED, approval_id=approval_id)


def _report_line_audit_detail(parked: Mapping[str, object]) -> dict[str, str]:
    route = parked.get("report_line_route")
    if not isinstance(route, Mapping):
        return {}
    fields = {
        "report_line_route_digest": route.get("route_digest"),
        "report_line_path_revision": route.get("path_revision"),
        "report_line_graph_revision": route.get("graph_revision"),
    }
    return {key: value for key, value in fields.items() if isinstance(value, str) and value}


__all__ = [
    "HilResumeCoordinator",
    "RequestApprovalResult",
    "RequestOutcome",
    "ResolveOutcome",
    "ResolveResult",
]
