"""Safety-critical control-loop orchestration.

Events flow through ingest, trust routing, T0/T1/T2 evaluation, the
quality and risk gates, HIL parking, execution, and append-only audit.
Optional seams fail closed and preserve shadow-mode invariants.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

# G-2: module-level helpers extracted into _helpers.py for testability.
from fdai.core.control_loop._helpers import (
    _extract_resource_id,
    _extract_resource_props,
    _is_execution_success,
    _synthetic_action_build_failure,
    _unified_audit_dict,
    build_shadow_authority_audit,
    evaluate_unified,
)
from fdai.core.event_ingest import EventCorrelator, EventIngest
from fdai.core.executor import ExecutionResult, ShadowExecutor
from fdai.core.executor.action_builder import ActionBuilder, ActionBuildError
from fdai.core.executor.direct_api import (
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.notifications.renderer import default_catalog
from fdai.core.notifications.router import NotificationRouter
from fdai.core.quality_gate import quality_decision_audit_fields
from fdai.core.rca import (
    Citation,
    CitationKind,
    IncidentMemberSource,
    RcaCoordinator,
)
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t1_lightweight.tier import T1Decision, T1Outcome, T1Tier
from fdai.core.tiers.t2_reasoning import (
    T2Decision,
    T2Outcome,
    T2ProposalContext,
    T2Tier,
)
from fdai.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from fdai.core.verticals.change_safety.detector import (
    ChangeSafetyDecision,
    ChangeSafetyDetector,
)
from fdai.core.workflow.coordinator import WorkflowTriggerCoordinator
from fdai.rule_catalog.schema.assignment import (
    Assignment,
    AssignmentResolution,
    resolve_assignments,
)
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.rule_catalog.schema.scope import ResourceContext
from fdai.shared.contracts.models import (
    Action,
    Event,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Rule,
)
from fdai.shared.providers.cost_estimator import (
    CostEstimator,
    resolve_cost_impact_monthly,
)
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)
from fdai.shared.providers.stage_publisher import (
    NullStagePublisher,
    StageEvent,
    StageName,
    StagePhase,
    StagePublisher,
)
from fdai.shared.providers.state_store import StateStore
from fdai.shared.resilience import DegradationController, KillSwitch

_LOGGER = logging.getLogger(__name__)

# Submitter identity recorded on a HIL park raised by the autonomous
# control loop. The loop has no human principal (the event was detected,
# not operator-requested), so any real approver differs from this value
# and the no-self-approval invariant is satisfied structurally.
_HIL_SYSTEM_SUBMITTER = "system:control-loop"


class ControlLoopOutcome(StrEnum):
    """Top-level outcome for one :meth:`ControlLoop.process` call."""

    DEDUPED = "deduped"
    ABSTAINED_ROUTING = "abstained_routing"
    ABSTAINED_T0 = "abstained_t0"
    EXECUTED = "executed"
    ABSTAINED_ACTION_BUILD = "abstained_action_build"
    GOVERNANCE_OBSERVED = "governance_observed"
    HIL = "hil"
    DENIED = "denied"
    T1_REUSE_LOGGED = "t1_reuse_logged"
    T1_ABSTAINED = "t1_abstained"
    T2_PROPOSED_LOGGED = "t2_proposed_logged"
    T2_ESCALATED = "t2_escalated"
    T2_DENIED = "t2_denied"
    T2_ABSTAINED = "t2_abstained"


@dataclass(frozen=True, slots=True)
class ControlLoopResult:
    """Aggregate typed result for one event."""

    outcome: ControlLoopOutcome
    tier: str
    decision: str
    resource_type: str | None
    citing_rule_ids: tuple[str, ...] = ()
    execution_results: tuple[
        ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult, ...
    ] = ()
    reason: str | None = None
    event_id: str | None = None
    change_safety_decision: ChangeSafetyDecision | None = None
    t1_decision: T1Decision | None = None
    t2_decision: T2Decision | None = None


_T2_OUTCOME_MAP: Mapping[T2Outcome, ControlLoopOutcome] = {
    T2Outcome.PROPOSED: ControlLoopOutcome.T2_PROPOSED_LOGGED,
    T2Outcome.ESCALATE: ControlLoopOutcome.T2_ESCALATED,
    T2Outcome.DENIED: ControlLoopOutcome.T2_DENIED,
    T2Outcome.ABSTAIN: ControlLoopOutcome.T2_ABSTAINED,
}


class ControlLoop:
    """One-call orchestrator for the P1 pipeline."""

    def __init__(
        self,
        *,
        event_ingest: EventIngest,
        trust_router: TrustRouter,
        t0_engine: T0Engine,
        action_builder: ActionBuilder,
        executor: ShadowExecutor,
        audit_store: StateStore,
        rules_by_id: Mapping[str, Rule],
        change_safety_detector: ChangeSafetyDetector | None = None,
        risk_table: RiskTable | None = None,
        action_types_by_name: Mapping[str, OntologyActionType] | None = None,
        risk_gate: RiskGate | None = None,
        cost_estimator: CostEstimator | None = None,
        direct_api_executor: DirectApiShadowExecutor | None = None,
        tool_executor: ToolCallShadowExecutor | None = None,
        t1_engine: T1Tier | None = None,
        t2_engine: T2Tier | None = None,
        stage_publisher: StagePublisher | None = None,
        notification_router: NotificationRouter | None = None,
        hil_resume_coordinator: HilResumeCoordinator | None = None,
        rca_coordinator: RcaCoordinator | None = None,
        event_correlator: EventCorrelator | None = None,
        incident_member_source: IncidentMemberSource | None = None,
        causal_chain_window: timedelta | None = None,
        resource_dependency_graph: Mapping[str, Iterable[str]] | None = None,
        workflow_coordinator: WorkflowTriggerCoordinator | None = None,
        degradation: DegradationController | None = None,
        kill_switch: KillSwitch | None = None,
        governance_assignments: Iterable[Assignment] = (),
        inventory_age_provider: Callable[[str], Awaitable[int | None]] | None = None,
        promotion_state_refresher: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._event_ingest = event_ingest
        self._trust_router = trust_router
        self._t0_engine = t0_engine
        self._action_builder = action_builder
        self._executor = executor
        self._audit_store = audit_store
        self._rules_by_id = dict(rules_by_id)
        self._change_safety_detector = change_safety_detector
        self._risk_table = risk_table
        self._action_types_by_name = (
            dict(action_types_by_name) if action_types_by_name is not None else {}
        )
        self._risk_gate = risk_gate
        self._degradation = degradation
        self._kill_switch = kill_switch
        self._governance_assignments = tuple(governance_assignments)
        self._inventory_age_provider = inventory_age_provider
        self._promotion_state_refresher = promotion_state_refresher
        self._cost_estimator = cost_estimator
        self._direct_api_executor = direct_api_executor
        self._tool_executor = tool_executor
        self._t1_engine = t1_engine
        self._t2_engine = t2_engine
        self._stage_publisher: StagePublisher = stage_publisher or NullStagePublisher()
        self._notification_router = notification_router
        self._hil_resume_coordinator = hil_resume_coordinator
        self._rca_coordinator = rca_coordinator
        self._event_correlator = event_correlator
        self._incident_member_source = incident_member_source
        self._causal_chain_window = causal_chain_window or timedelta(minutes=15)
        self._resource_dependency_graph = (
            dict(resource_dependency_graph) if resource_dependency_graph is not None else None
        )
        self._workflow_coordinator = workflow_coordinator

    async def _maybe_fire_workflows(self, event: Event) -> None:
        """Fire any Workflows the ingested event triggers, in shadow.

        A pure side-consumer: matched Workflows judge-and-log (they cannot
        mutate) and write their own audit rows. A coordinator failure is
        logged and swallowed so it never breaks the primary control decision -
        the same fail-safe-on-notification posture the router and HIL park
        already use.
        """
        if self._workflow_coordinator is None:
            return
        try:
            await self._workflow_coordinator.on_event(event)
        except Exception as exc:  # noqa: BLE001 - shadow side-consumer never breaks the loop
            _LOGGER.warning(
                "workflow_coordinator_failed",
                extra={"event_type": event.event_type, "error": type(exc).__name__},
            )

    async def process(self, raw_event: Event | Mapping[str, Any]) -> ControlLoopResult:
        # 1. Ingest + dedupe
        event = self._event_ingest.ingest(raw_event)
        if event is None:
            # No usable Event -> no stable id to emit against, so we do
            # NOT publish a stage event on the dedupe path. Duplicates
            # are also no-op for the audit log (the earlier delivery
            # owns the audit row).
            return ControlLoopResult(
                outcome=ControlLoopOutcome.DEDUPED,
                tier="abstain",
                decision="dedupe",
                resource_type=None,
                reason="duplicate_idempotency_key",
            )

        # Stable ids for every emit below. Fall back to event_id when
        # the event carries no correlation_id (single-shot events).
        event_id = str(event.event_id)
        correlation_id = event.correlation_id or event_id
        incident_id = self._correlate_incident_id(event)

        # ingest.done - the event survived dedup and is a valid Event.
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.INGEST,
            phase=StagePhase.DONE,
            detail={"event_type": event.event_type, "mode": event.mode.value},
        )

        # 1z. Optional process-automation side-consumer. Fires matched
        # Workflows in shadow off the ingested event. Pure side-effect
        # (audit rows only); never changes routing or the return path.
        await self._maybe_fire_workflows(event)

        # 1a. Optional Change Safety out-of-band detector.
        #
        # Runs BEFORE the trust router for Activity Log signals; every
        # other signal passes through unchanged (per phase-1 doc §
        # Out-of-Band Detection). The detector never blocks primary
        # routing - it is a shadow-mode observability + reconcile-PR
        # emitter.
        cs_decision: ChangeSafetyDecision | None = None
        if (
            self._change_safety_detector is not None
            and self._change_safety_detector.is_activity_log(event)
        ):
            cs_decision = await self._change_safety_detector.detect(event)

        # 2. Route
        decision = self._trust_router.route(event)
        if decision.tier is RoutingTier.ABSTAIN:
            await self._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.ROUTE,
                phase=StagePhase.DONE,
                detail={
                    "routed_to": "abstain",
                    "resource_type": decision.resource_type,
                    "reason": decision.reason or "trust_router_abstain",
                },
            )
            await self._write_abstain_audit(
                event=event,
                decision=decision,
                reason=decision.reason or "trust_router_abstain",
                stage="trust_router",
            )
            await self._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.AUDIT,
                phase=StagePhase.DONE,
                detail={"outcome": ControlLoopOutcome.ABSTAINED_ROUTING.value},
            )
            return ControlLoopResult(
                outcome=ControlLoopOutcome.ABSTAINED_ROUTING,
                tier="abstain",
                decision="abstain",
                resource_type=decision.resource_type,
                citing_rule_ids=decision.candidate_rule_ids,
                reason=decision.reason,
                event_id=str(event.event_id),
                change_safety_decision=cs_decision,
            )

        if decision.resource_type is None:  # pragma: no cover - belt-and-suspenders
            # The router MUST populate resource_type for T0 decisions;
            # this branch is unreachable via the public API.
            raise RuntimeError("trust router returned T0 without a resource_type")

        # route.done - routed to a real tier.
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.ROUTE,
            phase=StagePhase.DONE,
            detail={
                "routed_to": decision.tier.value,
                "resource_type": decision.resource_type,
                "candidate_rule_ids": list(decision.candidate_rule_ids),
            },
        )

        if decision.tier is RoutingTier.T1:
            await self._write_abstain_audit(
                event=event,
                decision=decision,
                reason=decision.reason or "no_rule_matches_resource_type",
                stage="trust_router",
            )
            fallback = await self._evaluate_fallback_tiers(
                event=event,
                decision=decision,
                citing=(),
                cs_decision=cs_decision,
                event_id=event_id,
                correlation_id=correlation_id,
            )
            if fallback is not None:
                return fallback
            await self._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.AUDIT,
                phase=StagePhase.DONE,
                detail={"outcome": ControlLoopOutcome.ABSTAINED_ROUTING.value},
            )
            return ControlLoopResult(
                outcome=ControlLoopOutcome.ABSTAINED_ROUTING,
                tier="t1",
                decision="abstain",
                resource_type=decision.resource_type,
                reason=decision.reason,
                event_id=event_id,
                change_safety_decision=cs_decision,
            )

        # 3. Evaluate T0
        resource_props = _extract_resource_props(event.payload)
        resource_id = _extract_resource_id(event, decision)
        verdict = self._t0_engine.evaluate(
            event_id=str(event.event_id),
            signal_id=str(event.event_id),
            resource_id=resource_id,
            resource_type=decision.resource_type,
            resource_props=resource_props,
            signal_type=event.event_type,
        )
        citing = verdict.audit_hint.citing_rule_ids if verdict.audit_hint else ()
        # verify.done for T0 - always emit once T0 has evaluated.
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.VERIFY,
            phase=StagePhase.DONE,
            detail={
                "tier": "t0",
                "matched": verdict.matched,
                "citing_rule_ids": list(citing),
            },
        )
        if not verdict.matched:
            await self._write_abstain_audit(
                event=event,
                decision=decision,
                reason=(
                    verdict.audit_hint.reason
                    if verdict.audit_hint and verdict.audit_hint.reason
                    else "t0_no_match"
                ),
                stage="t0_evaluate",
            )
            await self._analyze_t2_rca_on_abstain(
                event=event, decision=decision, incident_id=incident_id
            )

            fallback = await self._evaluate_fallback_tiers(
                event=event,
                decision=decision,
                citing=citing,
                cs_decision=cs_decision,
                event_id=event_id,
                correlation_id=correlation_id,
            )
            if fallback is not None:
                return fallback
            await self._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.AUDIT,
                phase=StagePhase.DONE,
                detail={"outcome": ControlLoopOutcome.ABSTAINED_T0.value},
            )
            return ControlLoopResult(
                outcome=ControlLoopOutcome.ABSTAINED_T0,
                tier="t0",
                decision="abstain",
                resource_type=decision.resource_type,
                citing_rule_ids=citing,
                reason=verdict.audit_hint.reason if verdict.audit_hint else None,
                event_id=str(event.event_id),
                change_safety_decision=cs_decision,
            )

        # T1 temporal causal-chain RCA for the matched incident (the "why"
        # behind the failure), shadow-only and best-effort. Runs once per
        # event, before the per-finding loop, so the chain is not
        # re-derived for every finding.
        await self._analyze_and_audit_t1_causal_chain(event=event, incident_id=incident_id)

        # 4. Evaluate + route + execute one action per finding
        exec_results: list[
            ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult
        ] = []
        routed: list[str] = []
        for finding in verdict.findings:
            rule = self._rules_by_id.get(finding.rule_id)
            if rule is None:  # pragma: no cover - index/catalog inconsistency
                raise KeyError(
                    f"rule {finding.rule_id!r} appears in T0 findings but is "
                    "not in the rules_by_id map"
                )
            assignment = self._resolve_governance_assignment(
                event=event,
                resource_id=finding.resource_id,
                resource_type=decision.resource_type,
                rule_id=rule.id,
            )
            if assignment is not None:
                await self._write_governance_assignment_audit(
                    event=event,
                    resource_id=finding.resource_id,
                    resolution=assignment,
                )
                if assignment.parameter_tie:
                    routed.append("hil")
                    continue
                if assignment.effective_effect is Effect.DENY:
                    routed.append(
                        "deny" if assignment.enforcement is Enforcement.ENFORCE else "hil"
                    )
                    continue
                if assignment.effective_effect in (Effect.DISABLED, Effect.AUDIT):
                    routed.append("governance_observe")
                    continue
                if assignment.enforcement is not Enforcement.ENFORCE:
                    routed.append("governance_observe")
                    continue
                if assignment.parameters:
                    rule = rule.model_copy(
                        update={
                            "parameters": {
                                **rule.parameters,
                                **dict(assignment.parameters),
                            }
                        }
                    )
            await self._analyze_and_audit_rca(
                event=event,
                finding=finding,
                rule=rule,
                resource_type=decision.resource_type,
                incident_id=incident_id,
            )
            try:
                action = self._action_builder.build_from_finding(
                    event=event, finding=finding, rule=rule
                )
            except ActionBuildError as exc:
                # Fail-closed for this finding; other findings keep going.
                await self._emit_stage(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.GATE,
                    phase=StagePhase.FAILED,
                    detail={"rule_id": finding.rule_id, "stage": "action_build"},
                    error=str(exc),
                )
                await self._write_abstain_audit(
                    event=event,
                    decision=decision,
                    reason=str(exc),
                    stage="action_build",
                )
                exec_results.append(  # noqa: E501 - surfaces the failure to the caller
                    _synthetic_action_build_failure(event=event, finding=finding, reason=str(exc))
                )
                continue

            unified = await self._evaluate_and_audit(event=event, action=action, rule=rule)
            gate_decision = (
                "deny"
                if unified is not None and unified.is_denied
                else "hil"
                if unified is not None and unified.requires_hil
                else "auto"
            )
            await self._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.GATE,
                phase=StagePhase.DONE,
                detail={
                    "rule_id": finding.rule_id,
                    "action_type": action.action_type,
                    "gate_decision": gate_decision,
                    "mode": action.mode.value,
                },
            )
            if unified is not None and (unified.is_denied or unified.requires_hil):
                # Routed to HIL / denied by the unified risk gate: do NOT
                # publish a PR. The audit entry (written above) records why.
                routed.append("deny" if unified.is_denied else "hil")
                if (
                    unified.requires_hil
                    and not unified.is_denied
                    and self._hil_resume_coordinator is not None
                ):
                    await self._request_hil_approval(
                        action=action,
                        rule=rule,
                        correlation_id=correlation_id,
                    )
                continue
            result = await self._dispatch_action(action=action, rule=rule)
            exec_results.append(result)
            # execute.done / execute.failed per action.
            exec_success = _is_execution_success(result)
            exec_stage_detail: dict[str, Any] = {
                "rule_id": finding.rule_id,
                "action_type": action.action_type,
                "mode": action.mode.value,
            }
            if exec_success:
                await self._emit_stage(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.EXECUTE,
                    phase=StagePhase.DONE,
                    detail=exec_stage_detail,
                )
            else:
                await self._emit_stage(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.EXECUTE,
                    phase=StagePhase.FAILED,
                    detail=exec_stage_detail,
                    error=getattr(result, "reason", None) or "execution_failed",
                )

        # If EVERY finding hit a build error, treat the overall outcome
        # as ABSTAINED_ACTION_BUILD so a monitor can page on it.
        if "deny" in routed:
            overall = ControlLoopOutcome.DENIED
        elif "hil" in routed:
            overall = ControlLoopOutcome.HIL
        elif any(_is_execution_success(r) for r in exec_results):
            overall = ControlLoopOutcome.EXECUTED
        elif "governance_observe" in routed:
            overall = ControlLoopOutcome.GOVERNANCE_OBSERVED
        else:
            overall = ControlLoopOutcome.ABSTAINED_ACTION_BUILD
        decision_word = {
            ControlLoopOutcome.DENIED: "deny",
            ControlLoopOutcome.HIL: "hil",
            ControlLoopOutcome.EXECUTED: "auto",
        }.get(overall, "abstain")
        # audit.done - seals the pipeline so the live view can settle a
        # tile on the final decision word.
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.AUDIT,
            phase=StagePhase.DONE,
            detail={
                "outcome": overall.value,
                "decision": decision_word,
                "gate_decision": decision_word,
                "mode": event.mode.value,
            },
        )
        await self._notify_decision(
            event=event,
            correlation_id=correlation_id,
            overall=overall,
            decision_word=decision_word,
            resource_type=decision.resource_type,
            citing_rule_ids=tuple(f.rule_id for f in verdict.findings),
        )
        return ControlLoopResult(
            outcome=overall,
            tier="t0",
            decision=decision_word,
            resource_type=decision.resource_type,
            citing_rule_ids=tuple(f.rule_id for f in verdict.findings),
            execution_results=tuple(exec_results),
            event_id=str(event.event_id),
            change_safety_decision=cs_decision,
        )

    def _resolve_governance_assignment(
        self,
        *,
        event: Event,
        resource_id: str,
        resource_type: str,
        rule_id: str,
    ) -> AssignmentResolution | None:
        if not self._governance_assignments:
            return None
        payload = event.payload
        resource = payload.get("resource")
        resource_data = resource if isinstance(resource, dict) else {}
        props = resource_data.get("props")
        props_data = props if isinstance(props, dict) else {}
        tags = props_data.get("tags")
        tag_data = tags if isinstance(tags, dict) else {}

        def _text(*keys: str) -> str:
            for key in keys:
                value = resource_data.get(key, payload.get(key))
                if isinstance(value, str) and value:
                    return value
            return ""

        context = ResourceContext(
            organization=_text("organization", "tenant_id"),
            account=_text("account", "subscription_id"),
            resource_group=_text("resource_group"),
            resource_id=resource_id,
            resource_type=resource_type,
            tags={str(key): str(value) for key, value in tag_data.items()},
        )
        return resolve_assignments(
            assignments=self._governance_assignments,
            ctx=context,
            rule_id=rule_id,
        )

    async def _write_governance_assignment_audit(
        self,
        *,
        event: Event,
        resource_id: str,
        resolution: AssignmentResolution,
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "actor": "fdai.core.control_loop",
                "action_kind": "governance.assignment_resolved",
                "mode": Mode.SHADOW.value,
                "rule_id": resolution.rule_id,
                "resource_id": resource_id,
                "effective_effect": resolution.effective_effect.value,
                "enforcement": resolution.enforcement.value,
                "winning_assignment_id": resolution.winning_assignment_id,
                "overridden_assignment_ids": list(resolution.overridden_assignment_ids),
                "parameter_tie": resolution.parameter_tie,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

    async def _notify_decision(
        self,
        *,
        event: Event,
        correlation_id: str,
        overall: ControlLoopOutcome,
        decision_word: str,
        resource_type: str | None,
        citing_rule_ids: tuple[str, ...],
    ) -> None:
        """Push one outbound A2 operational-alert for a terminal decision.

        No-op unless a :class:`NotificationRouter` is wired. Only the
        three actionable outcomes (``EXECUTED`` / ``HIL`` / ``DENIED``)
        notify - abstain, dedupe, and T1-shadow paths are silent so a
        healthy no-op stream never pages the ops lane.

        The message body is intentionally generic (decision, resource
        *type*, citing rule ids, shadow mode) and carries NO
        customer-identifying value - no resource id, tenant, or payload
        (per generic-scope + channels-and-notifications.md 1.5). A2 is
        outbound-only: the message carries links only, never approval
        buttons; the HIL approval round-trip is the separate A1 channel.

        Best-effort: any dispatch error is logged and swallowed so a
        notification outage cannot invalidate the already-audited
        control decision.
        """
        if self._notification_router is None:
            return
        severity_by_outcome = {
            ControlLoopOutcome.EXECUTED: Severity.INFO,
            ControlLoopOutcome.HIL: Severity.WARN,
            ControlLoopOutcome.DENIED: Severity.ERROR,
        }
        severity = severity_by_outcome.get(overall)
        if severity is None:
            return  # not an actionable terminal outcome; stay silent
        rules_line = ", ".join(citing_rule_ids) if citing_rule_ids else "n/a"
        notify_params = {
            "decision": decision_word,
            "resource_title": resource_type or "unknown",
            "resource_body": resource_type or "n/a",
            "rules": rules_line,
            "mode": Mode.SHADOW.value,
        }
        # Render English here for the audit entry + as the fallback; the router
        # re-renders per destination-channel locale (notifications Option C).
        title, body_markdown = default_catalog().render("decision", notify_params, "en")
        message = NotificationMessage(
            category="operational_alert",
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            correlation_id=correlation_id,
            title=title,
            body_markdown=body_markdown,
            template_key="decision",
            params=notify_params,
            severity=severity,
            metadata={
                "outcome": overall.value,
                "decision": decision_word,
                "event_id": str(event.event_id),
            },
        )
        try:
            await self._notification_router.dispatch(message)
        except Exception:  # noqa: BLE001 - push is best-effort; decision already audited
            _LOGGER.warning(
                "notify_decision_dispatch_failed",
                extra={
                    "correlation_id": correlation_id,
                    "outcome": overall.value,
                },
                exc_info=True,
            )

    async def _request_hil_approval(
        self,
        *,
        action: Action,
        rule: Rule,
        correlation_id: str,
    ) -> None:
        """Park a HIL-routed action and push an A1 approval card.

        Best-effort at the loop boundary: a park/push failure is logged
        and swallowed. A failure NEVER turns a HIL verdict into an
        execution - the action simply stays un-parked and the HIL audit
        row (already written by the gate) records that no PR was
        published. The parked action awaits an explicit approve/reject
        via :meth:`HilResumeCoordinator.resolve`.
        """
        if self._hil_resume_coordinator is None:  # pragma: no cover - guarded by caller
            return
        try:
            await self._hil_resume_coordinator.request_approval(
                action=action,
                rule=rule,
                submitter_oid=_HIL_SYSTEM_SUBMITTER,
                correlation_id=correlation_id,
            )
        except Exception:  # noqa: BLE001 - park/push best-effort; HIL stays fail-closed
            _LOGGER.warning(
                "hil_request_approval_failed",
                extra={
                    "correlation_id": correlation_id,
                    "action_type": action.action_type,
                },
                exc_info=True,
            )

    def _correlate_incident_id(self, event: Event) -> str | None:
        """Anchor an event to a deterministic incident id, or ``None``.

        No-op unless an :class:`EventCorrelator` is wired. An
        uncorrelatable event (no correlation_id, no resource ref) yields
        ``None`` so the RCA audit simply omits the incident context.
        Pure and side-effect-free - the id is derived from the event's
        keys + window bucket.
        """
        if self._event_correlator is None:
            return None
        result = self._event_correlator.correlate(event)
        return result.incident_id if result.correlated else None

    async def _analyze_and_audit_rca(
        self,
        *,
        event: Event,
        finding: Any,
        rule: Rule,
        resource_type: str | None,
        incident_id: str | None = None,
    ) -> None:
        """Append a deterministic T0 root-cause hypothesis to the audit.

        No-op unless an :class:`RcaCoordinator` is wired. The hypothesis
        is the "why" behind the finding (the matched rule names the
        violated control); it never changes the executor path. Best-
        effort: any failure is logged and swallowed so RCA can never
        block or invalidate the control decision.
        """
        if self._rca_coordinator is None:
            return
        try:
            result = self._rca_coordinator.analyze_t0(
                rule=rule,
                resource_type=resource_type or "unknown",
                event_id=str(event.event_id),
            )
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca:{finding.rule_id}",
                    "actor": "fdai.core.rca",
                    "action_kind": "rca.hypothesis",
                    "mode": Mode.SHADOW.value,
                    "rule_id": finding.rule_id,
                    "incident_id": incident_id,
                    "rca_outcome": result.outcome.value,
                    "rca_reason": result.reason,
                    "rca_tier": hypothesis.tier.value if hypothesis else None,
                    "rca_cause": hypothesis.cause if hypothesis else None,
                    "rca_confidence": hypothesis.confidence if hypothesis else None,
                    "rca_citations": (
                        [{"kind": c.kind.value, "ref": c.ref} for c in hypothesis.citations]
                        if hypothesis
                        else []
                    ),
                    "rca_remediation_ref": hypothesis.remediation_ref if hypothesis else None,
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - RCA is best-effort; decision path unaffected
            _LOGGER.warning(
                "rca_analyze_failed",
                extra={"event_id": str(event.event_id), "rule_id": finding.rule_id},
                exc_info=True,
            )

    async def _analyze_and_audit_t1_causal_chain(
        self,
        *,
        event: Event,
        incident_id: str | None,
    ) -> None:
        """Append a T1 temporal causal-chain hypothesis to the audit.

        No-op unless an :class:`RcaCoordinator`, an
        :class:`IncidentMemberSource`, an ``incident_id``, and a failure
        ``resource_ref`` are all present. Reconstructs the most probable
        ``root change -> ... -> failure`` chain from the incident's member
        events and records it as a shadow ``rca.hypothesis`` (tier t1) -
        the "why", never a new execution path. Best-effort: any failure is
        logged and swallowed so RCA can never block the control decision.
        """
        if (
            self._rca_coordinator is None
            or self._incident_member_source is None
            or incident_id is None
            or not event.resource_ref
        ):
            return
        try:
            members = await self._incident_member_source.members(incident_id=incident_id)
            if not members:
                # No incident history available (e.g. a no-op source or a
                # freshly-opened incident) - nothing to reconstruct. Skip
                # silently rather than emit a per-event abstain row.
                return
            result = self._rca_coordinator.analyze_t1_causal_chain(
                failure_event_id=str(event.event_id),
                failure_at=event.detected_at,
                failure_resource_ref=event.resource_ref,
                correlated_events=members,
                window=self._causal_chain_window,
                depends_on=self._resource_dependency_graph,
            )
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca_t1_chain",
                    "actor": "fdai.core.rca",
                    "action_kind": "rca.hypothesis",
                    "mode": Mode.SHADOW.value,
                    "incident_id": incident_id,
                    "rca_outcome": result.outcome.value,
                    "rca_reason": result.reason,
                    "rca_tier": hypothesis.tier.value if hypothesis else "t1",
                    "rca_cause": hypothesis.cause if hypothesis else None,
                    "rca_confidence": hypothesis.confidence if hypothesis else None,
                    "rca_citations": (
                        [{"kind": c.kind.value, "ref": c.ref} for c in hypothesis.citations]
                        if hypothesis
                        else []
                    ),
                    "rca_causal_chain": (
                        hypothesis.causal_chain.to_dict()
                        if hypothesis and hypothesis.causal_chain
                        else None
                    ),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - T1 causal-chain RCA best-effort
            _LOGGER.warning(
                "rca_t1_chain_analyze_failed",
                extra={"event_id": str(event.event_id), "incident_id": incident_id},
                exc_info=True,
            )

    async def _analyze_t2_rca_on_abstain(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        incident_id: str | None,
    ) -> None:
        """Append a grounded T2 root-cause hypothesis for a novel case.

        No-op unless an :class:`RcaCoordinator` with a T2 reasoner is
        wired (a deployment without an LLM never emits T2 noise). The
        reasoner's answer is grounded on the event/telemetry evidence
        supplied here and passes the grounding gate; an ungrounded or
        abstaining reasoner records an abstain. Best-effort - T2 RCA
        never blocks or changes the already-abstained control decision.
        """
        if self._rca_coordinator is None or not self._rca_coordinator.has_t2:
            return
        resource = event.resource_ref or _extract_resource_id(event, decision)
        candidates = [Citation(kind=CitationKind.EVENT, ref=str(event.event_id))]
        if resource:
            candidates.append(Citation(kind=CitationKind.TELEMETRY, ref=resource))
        try:
            summary = f"novel {event.event_type} on {decision.resource_type or 'unknown'}"
            result = await self._rca_coordinator.analyze_t2(
                incident_summary=summary,
                candidate_citations=tuple(candidates),
            )
            hypothesis = result.hypothesis
            await self._audit_store.append_audit_entry(
                {
                    "event_id": str(event.event_id),
                    "idempotency_key": f"{event.idempotency_key}:rca_t2",
                    "actor": "fdai.core.rca",
                    "action_kind": "rca.hypothesis",
                    "mode": Mode.SHADOW.value,
                    "incident_id": incident_id,
                    "rca_outcome": result.outcome.value,
                    "rca_reason": result.reason,
                    "rca_tier": hypothesis.tier.value if hypothesis else "t2",
                    "rca_cause": hypothesis.cause if hypothesis else None,
                    "rca_confidence": hypothesis.confidence if hypothesis else None,
                    "rca_citations": (
                        [{"kind": c.kind.value, "ref": c.ref} for c in hypothesis.citations]
                        if hypothesis
                        else []
                    ),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - T2 RCA best-effort; decision path unaffected
            _LOGGER.warning(
                "rca_t2_analyze_failed",
                extra={"event_id": str(event.event_id)},
                exc_info=True,
            )

    async def _emit_stage(
        self,
        *,
        event_id: str,
        correlation_id: str,
        stage: StageName,
        phase: StagePhase,
        detail: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Construct + emit one :class:`StageEvent`.

        Never raises: the adapters swallow their own transport errors,
        and a bad :class:`StageEvent` construction (invariant violation)
        is logged and dropped so the pipeline keeps going.
        """
        try:
            evt = StageEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=stage,
                phase=phase,
                detail=dict(detail) if detail else {},
                error=error,
            )
        except ValueError:  # pragma: no cover - defence in depth
            return
        await self._stage_publisher.emit(evt)

    async def _resolve_cost_override(
        self,
        *,
        rule: Rule,
        action_type: OntologyActionType,
    ) -> float | None:
        """Return the ``cost_impact_monthly`` override for the authority pipeline.

        Rule-declared static cost (``rule.remediation.cost_impact_monthly_usd``)
        always wins - the authority pipeline reads it directly in that
        case, so this returns ``None`` (no override).

        When the rule is silent AND a
        :class:`~fdai.shared.providers.cost_estimator.CostEstimator`
        is wired, the estimator is consulted. Any failure (abstain,
        transport error, ``None`` estimator) surfaces as ``None`` -
        the Axis A rule treats unknown cost as "route to HIL", per the
        fail-closed cost-gate contract in
        ``docs/roadmap/decisioning/execution-model.md § 2.8``.
        """

        if rule.remediation.cost_impact_monthly_usd is not None:
            return None  # rule value is authoritative; do not override
        if self._cost_estimator is None:
            return None
        return await resolve_cost_impact_monthly(self._cost_estimator, action_type, arguments=None)

    async def _dispatch_action(
        self, *, action: Action, rule: Rule
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        """Route ``action`` to the executor its ActionType declares.

        Selection rule (composition wire):

        - ``execution_path == direct_api`` AND a direct-API executor is
          wired -> :class:`DirectApiShadowExecutor`.
        - ``execution_path == tool_call`` AND a tool executor is wired ->
          :class:`ToolCallShadowExecutor`.
        - Otherwise -> the PR-native :class:`ShadowExecutor`.

        The default (neither sibling wired) keeps every action on the
        PR-native path so a composition that has no substrate/tool
        adapter still functions - this matches the P1 upstream
        behaviour. Only ActionTypes that opt in via the ontology reach a
        sibling.

        Observability guard: when an ActionType opts into ``direct_api``
        or ``tool_call`` but the matching executor is NOT wired, the
        action falls back to the PR-native executor, which cannot render
        a non-PR action - so we emit a warning rather than let the
        dispatch fail silently downstream.
        """

        action_type = self._action_types_by_name.get(action.action_type)
        path = action_type.execution_path if action_type is not None else None

        if path is ExecutionPath.DIRECT_API and self._direct_api_executor is not None:
            return await self._direct_api_executor.execute(action=action)
        if path is ExecutionPath.TOOL_CALL and self._tool_executor is not None:
            return await self._tool_executor.execute(action=action)
        if path in (ExecutionPath.DIRECT_API, ExecutionPath.TOOL_CALL):
            _LOGGER.warning(
                "action_type opts into %s but no matching executor is wired; "
                "falling back to PR-native (which cannot render this path)",
                path.value,
                extra={
                    "action_type": action.action_type,
                    "execution_path": path.value,
                    "idempotency_key": action.idempotency_key,
                },
            )
        return await self._executor.execute(action=action, rule=rule)

    async def _write_abstain_audit(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        reason: str,
        stage: str,
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "actor": "fdai.core.control_loop",
                "action_kind": "control_loop.abstain",
                "mode": Mode.SHADOW.value,
                "stage": stage,
                "reason": reason,
                "resource_type": decision.resource_type,
                "candidate_rule_ids": list(decision.candidate_rule_ids),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

    async def record_unhandled_failure(
        self,
        *,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        """Record an unexpected process-boundary failure without raw payload data."""
        event_id = payload.get("event_id") or payload.get("id") or "unknown"
        idempotency_key = payload.get("idempotency_key") or "unknown"
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event_id),
                "idempotency_key": str(idempotency_key),
                "actor": "fdai.core.control_loop",
                "action_kind": "control_loop.unhandled_failure",
                "mode": Mode.SHADOW.value,
                "decision": "abstain",
                "reason": reason,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

    async def _write_t1_audit(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        t1: T1Decision,
    ) -> None:
        """Record the T1 similarity outcome as a shadow-only audit row.

        Called after T0 abstains AND ``t1_engine`` is wired. The row
        makes the T1 verdict + best-match diagnostics visible on the
        audit chain so an operator can measure "would-have-reused"
        rate without T1 ever mutating anything.
        """
        best = t1.best_match
        best_summary: dict[str, Any] | None = None
        if best is not None:
            best_summary = {
                "score": best.score,
                "rule_id": best.action.rule_id,
                "action_type": best.action.action_type,
                "success_rate": best.action.success_rate,
            }
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "actor": "fdai.core.control_loop",
                "action_kind": "control_loop.t1_evaluate",
                "mode": Mode.SHADOW.value,
                "stage": "t1_similarity",
                "t1_outcome": t1.outcome.value,
                "t1_threshold": t1.threshold,
                "t1_reason": t1.reason,
                "t1_reasons": list(t1.reasons),
                "t1_best_match": best_summary,
                "resource_type": decision.resource_type,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

    async def _evaluate_fallback_tiers(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        citing: tuple[str, ...],
        cs_decision: ChangeSafetyDecision | None,
        event_id: str,
        correlation_id: str,
    ) -> ControlLoopResult | None:
        t1_decision: T1Decision | None = None
        if self._t1_engine is not None:
            t1_decision = await self._t1_engine.evaluate(event=event)
            await self._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.VERIFY,
                phase=StagePhase.DONE,
                detail={
                    "tier": "t1",
                    "t1_outcome": t1_decision.outcome.value,
                    "reason": t1_decision.reason,
                },
            )
            await self._write_t1_audit(event=event, decision=decision, t1=t1_decision)
            if t1_decision.outcome is T1Outcome.REUSED:
                await self._emit_stage(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.AUDIT,
                    phase=StagePhase.DONE,
                    detail={"outcome": ControlLoopOutcome.T1_REUSE_LOGGED.value},
                )
                return ControlLoopResult(
                    outcome=ControlLoopOutcome.T1_REUSE_LOGGED,
                    tier="t1",
                    decision="abstain",
                    resource_type=decision.resource_type,
                    citing_rule_ids=citing,
                    reason="t1_reuse_requires_reverification",
                    event_id=event_id,
                    change_safety_decision=cs_decision,
                    t1_decision=t1_decision,
                )

        t2_result = await self._consult_t2(
            event=event,
            decision=decision,
            citing=citing,
            cs_decision=cs_decision,
            t1_decision=t1_decision,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        if t2_result is not None:
            return t2_result
        if t1_decision is None:
            return None
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.AUDIT,
            phase=StagePhase.DONE,
            detail={"outcome": ControlLoopOutcome.T1_ABSTAINED.value},
        )
        return ControlLoopResult(
            outcome=ControlLoopOutcome.T1_ABSTAINED,
            tier="t1",
            decision="abstain",
            resource_type=decision.resource_type,
            citing_rule_ids=citing,
            reason=t1_decision.reason or "t1_no_neighbour",
            event_id=event_id,
            change_safety_decision=cs_decision,
            t1_decision=t1_decision,
        )

    async def _consult_t2(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        citing: tuple[str, ...],
        cs_decision: ChangeSafetyDecision | None,
        t1_decision: T1Decision | None,
        event_id: str,
        correlation_id: str,
    ) -> ControlLoopResult | None:
        """Consult the T2 reasoning tier after T0 (and T1) abstained.

        Returns a T2 :class:`ControlLoopResult` when ``t2_engine`` is wired,
        or ``None`` when it is not (the caller then falls through to its
        existing T1-abstained / T0-abstained return - backward-compatible).

        Shadow-only: every T2 verdict is audited but nothing executes here.
        The audit ``decision`` stays ``abstain`` for all four outcomes because
        no action was built or routed - the outcome enum + ``t2_decision``
        carry the actual gate verdict, exactly as :attr:`T1_REUSE_LOGGED`
        records a reuse without executing it.
        """
        if self._t2_engine is None:
            return None
        target_ref = event.resource_ref
        resource = event.payload.get("resource")
        if not target_ref and isinstance(resource, dict):
            candidate_ref = resource.get("resource_id")
            if isinstance(candidate_ref, str) and candidate_ref:
                target_ref = candidate_ref
        if not target_ref or not decision.resource_type:
            return None
        allowed_rules = tuple(
            rule
            for rule_id in decision.candidate_rule_ids
            if (rule := self._rules_by_id.get(rule_id)) is not None
            and rule.resource_type == decision.resource_type
        )
        context = T2ProposalContext(
            event=event,
            target_resource_ref=target_ref,
            target_resource_type=decision.resource_type,
            allowed_rules=allowed_rules,
        )
        t2_decision = await self._t2_engine.evaluate(context=context)
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.VERIFY,
            phase=StagePhase.DONE,
            detail={
                "tier": "t2",
                "t2_outcome": t2_decision.outcome.value,
                "reason": t2_decision.reason,
            },
        )
        await self._write_t2_audit(event=event, decision=decision, t2=t2_decision)
        if t2_decision.outcome is T2Outcome.PROPOSED and t2_decision.candidate is not None:
            routed = await self._route_t2_candidate(
                event=event,
                decision=decision,
                t2=t2_decision,
                cs_decision=cs_decision,
                t1_decision=t1_decision,
                event_id=event_id,
                correlation_id=correlation_id,
            )
            if routed is not None:
                await self._emit_stage(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    stage=StageName.AUDIT,
                    phase=StagePhase.DONE,
                    detail={
                        "outcome": routed.outcome.value,
                        "decision": routed.decision,
                        "mode": Mode.SHADOW.value,
                    },
                )
                return routed
        outcome = _T2_OUTCOME_MAP[t2_decision.outcome]
        decision_word = {
            T2Outcome.PROPOSED: "abstain",
            T2Outcome.ESCALATE: "hil",
            T2Outcome.DENIED: "deny",
            T2Outcome.ABSTAIN: "hil",
        }[t2_decision.outcome]
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.AUDIT,
            phase=StagePhase.DONE,
            detail={"outcome": outcome.value, "decision": decision_word},
        )
        return ControlLoopResult(
            outcome=outcome,
            tier="t2",
            decision=decision_word,
            resource_type=decision.resource_type,
            citing_rule_ids=citing,
            reason=t2_decision.reason,
            event_id=str(event.event_id),
            change_safety_decision=cs_decision,
            t1_decision=t1_decision,
            t2_decision=t2_decision,
        )

    async def _route_t2_candidate(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        t2: T2Decision,
        cs_decision: ChangeSafetyDecision | None,
        t1_decision: T1Decision | None,
        event_id: str,
        correlation_id: str,
    ) -> ControlLoopResult | None:
        candidate = t2.candidate
        if candidate is None or self._risk_table is None or self._risk_gate is None:
            return None
        rule = next(
            (
                self._rules_by_id[rule_id]
                for rule_id in candidate.cited_rule_ids
                if rule_id in self._rules_by_id
            ),
            None,
        )
        if rule is None:
            return None
        try:
            action = self._action_builder.build_from_candidate(
                event=event,
                candidate=candidate,
            )
        except ActionBuildError as exc:
            await self._audit_store.append_audit_entry(
                {
                    "event_id": event_id,
                    "idempotency_key": event.idempotency_key,
                    "actor": "fdai.core.control_loop",
                    "action_kind": "control_loop.t2_action_build_abstain",
                    "mode": Mode.SHADOW.value,
                    "reason": str(exc),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
            return ControlLoopResult(
                outcome=ControlLoopOutcome.ABSTAINED_ACTION_BUILD,
                tier="t2",
                decision="abstain",
                resource_type=decision.resource_type,
                citing_rule_ids=candidate.cited_rule_ids,
                reason="t2_candidate_action_build_failed",
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1_decision,
                t2_decision=t2,
            )

        unified = await self._evaluate_and_audit(event=event, action=action, rule=rule)
        if unified is None:
            return None
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.GATE,
            phase=StagePhase.DONE,
            detail={
                "tier": "t2",
                "action_type": action.action_type,
                "gate_decision": unified.decision,
                "mode": action.mode.value,
            },
        )
        if unified.requires_hil and self._hil_resume_coordinator is not None:
            await self._request_hil_approval(
                action=action,
                rule=rule,
                correlation_id=correlation_id,
            )
        if unified.is_denied or unified.requires_hil:
            outcome = ControlLoopOutcome.DENIED if unified.is_denied else ControlLoopOutcome.HIL
            return ControlLoopResult(
                outcome=outcome,
                tier="t2",
                decision="deny" if unified.is_denied else "hil",
                resource_type=decision.resource_type,
                citing_rule_ids=candidate.cited_rule_ids,
                reason=t2.reason,
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1_decision,
                t2_decision=t2,
            )
        # SHADOW_ONLY is a measured proposal, not permission to dispatch.
        return None

    async def _write_t2_audit(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        t2: T2Decision,
    ) -> None:
        """Record the T2 reasoning outcome as a shadow-only audit row.

        Captures the gate verdict, the proposed ActionType + cited rules
        (when a candidate exists), and the aggregate confidence the gate
        derived - never the model's self-report - so a T2 judgment is
        reconstructable from the audit chain without the model text.
        """
        candidate_summary: dict[str, Any] | None = None
        if t2.candidate is not None:
            candidate_summary = {
                "action_type": t2.candidate.action_type,
                "target_resource_ref": t2.candidate.target_resource_ref,
                "cited_rule_ids": list(t2.candidate.cited_rule_ids),
            }
        quality_summary: dict[str, Any] | None = None
        if t2.quality_decision is not None:
            quality_summary = quality_decision_audit_fields(t2.quality_decision)
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "actor": "fdai.core.control_loop",
                "action_kind": "control_loop.t2_evaluate",
                "mode": Mode.SHADOW.value,
                "stage": "t2_reasoning",
                "t2_outcome": t2.outcome.value,
                "t2_reason": t2.reason,
                "t2_candidate": candidate_summary,
                "t2_quality": quality_summary,
                "resource_type": decision.resource_type,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )

    async def _evaluate_and_audit(
        self, *, event: Event, action: Action, rule: Rule
    ) -> UnifiedRiskDecision | None:
        """Evaluate the unified risk decision (when wired) and audit it.

        Returns the :class:`UnifiedRiskDecision` when a RiskGate is wired,
        so the caller can route on it (skip execution for hil / deny).
        Returns ``None`` for the authority-only or unwired cases
        (observation only; the caller executes exactly as before).
        """
        if self._risk_table is None:
            return None
        action_type = self._action_types_by_name.get(action.action_type)
        if action_type is None:
            return None
        if self._promotion_state_refresher is not None:
            await self._promotion_state_refresher(action_type.name)
        cost_override = await self._resolve_cost_override(rule=rule, action_type=action_type)
        system_degraded = (
            self._degradation is not None and not self._degradation.autonomy_permitted()
        )
        kill_switch_engaged = self._kill_switch is not None and self._kill_switch.is_engaged()
        inventory_age_seconds = None
        if self._inventory_age_provider is not None:
            try:
                inventory_age_seconds = await self._inventory_age_provider(
                    action.target_resource_ref
                )
            except Exception:  # noqa: BLE001 - freshness lookup fails closed
                _LOGGER.warning(
                    "inventory_age_lookup_failed",
                    extra={"action_type": action.action_type},
                    exc_info=True,
                )
        if self._risk_gate is not None:
            unified = evaluate_unified(
                event=event,
                action=action,
                rule=rule,
                action_type=action_type,
                table=self._risk_table,
                risk_gate=self._risk_gate,
                cost_override=cost_override,
                system_degraded=system_degraded,
                kill_switch_engaged=kill_switch_engaged,
                inventory_age_seconds=inventory_age_seconds,
            )
            entry = _unified_audit_dict(event=event, action=action, unified=unified)
            entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
            await self._audit_store.append_audit_entry(entry)
            return unified
        entry = build_shadow_authority_audit(
            event=event,
            action=action,
            rule=rule,
            action_type=action_type,
            table=self._risk_table,
            cost_override=cost_override,
            system_degraded=system_degraded,
            kill_switch_engaged=kill_switch_engaged,
        )
        entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
        await self._audit_store.append_audit_entry(entry)
        return None
