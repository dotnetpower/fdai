"""Control-loop orchestrator - wires the P1 pipeline end-to-end.

Composes the five P1 subsystems currently implemented:

.. code-block:: text

    event_ingest ──► trust_router ──► T0Engine ──► ActionBuilder ──► ShadowExecutor
                                       │
                                       └──► abstain-audit (fallback)

No T1 / T2 tier is invoked; those land in later phases behind their own
DI seams. The unified risk-gate pipeline
(:func:`fdai.core.risk_gate.authority.evaluate_execution_authority`)
is invoked **shadow-parallel** when a risk table is injected: it records
one ``risk_gate.shadow_authority`` audit entry per executed action
(judge-and-log only) and never changes the executor path. The
orchestrator lives in ``core/`` because it is
the safety-critical assembly point - every failure MUST audit, and
shadow-mode invariants hold for every path.

Contract (P1)
-------------

Every :meth:`ControlLoop.process` call:

- **Ingests** the event through :class:`EventIngest` (dedupe by
  ``idempotency_key``). A duplicate returns a
  :attr:`ControlLoopOutcome.DEDUPED` result and NO audit entry (the
  earlier delivery already wrote one).
- **Routes** through :class:`TrustRouter`. A non-T0 tier writes an
  ``abstain`` audit and returns :attr:`ControlLoopOutcome.ABSTAINED_ROUTING`.
- **Evaluates** T0. A no-match verdict writes an ``abstain`` audit and
  returns :attr:`ControlLoopOutcome.ABSTAINED_T0`.
- **Builds and executes** one :class:`Action` per finding. Each
  execution writes its own audit entry via the :class:`ShadowExecutor`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai.core.event_ingest import EventCorrelator, EventIngest
from fdai.core.executor import ExecutionResult, ExecutorOutcome, ShadowExecutor
from fdai.core.executor.action_builder import ActionBuilder, ActionBuildError
from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.notifications.renderer import default_catalog
from fdai.core.notifications.router import NotificationRouter
from fdai.core.rca import Citation, CitationKind, RcaCoordinator
from fdai.core.risk_gate.authority import (
    ExecutionAuthorityDecision,
    evaluate_execution_authority,
)
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision, combine
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.core.tiers.t0_deterministic import T0Engine
from fdai.core.tiers.t1_lightweight.tier import T1Decision, T1Outcome, T1Tier
from fdai.core.tiers.t2_reasoning import T2Decision, T2Outcome, T2Tier
from fdai.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from fdai.core.verticals.change_safety_detector import (
    ChangeSafetyDecision,
    ChangeSafetyDetector,
)
from fdai.core.workflow.coordinator import WorkflowTriggerCoordinator
from fdai.shared.contracts.models import (
    Action,
    CeilingRole,
    Event,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Rule,
    Tier,
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

_LOGGER = logging.getLogger(__name__)

# Submitter identity recorded on a HIL park raised by the autonomous
# control loop. The loop has no human principal (the event was detected,
# not operator-requested), so any real approver differs from this value
# and the no-self-approval invariant is satisfied structurally.
_HIL_SYSTEM_SUBMITTER = "system:control-loop"


class ControlLoopOutcome(StrEnum):
    """Top-level outcome for one :meth:`ControlLoop.process` call."""

    DEDUPED = "deduped"
    """Duplicate delivery - no audit written (previous delivery owns it)."""

    ABSTAINED_ROUTING = "abstained_routing"
    """Trust-router found no candidate rule; no T0 evaluation."""

    ABSTAINED_T0 = "abstained_t0"
    """T0 evaluated candidates and produced no findings."""

    EXECUTED = "executed"
    """One or more actions were built + executed (shadow PRs opened)."""

    ABSTAINED_ACTION_BUILD = "abstained_action_build"
    """A finding's ActionType could not be resolved; the loop fails
    closed instead of publishing an invalid Action."""

    HIL = "hil"
    """The unified risk gate routed one or more actions to human-in-the-
    loop. No shadow PR is published for those actions; they await
    approval. Only reachable when a RiskGate is wired in."""

    DENIED = "denied"
    """The unified risk gate denied one or more actions. No execution,
    no PR. Only reachable when a RiskGate is wired in."""

    T1_REUSE_LOGGED = "t1_reuse_logged"
    """T0 abstained; T1 similarity tier proposed a learned-action
    reuse. Shadow-only in P1: the reuse is recorded in the audit trail
    (with the similarity score + neighbour rule) but does NOT execute -
    the ``requires_reverification=True`` invariant on
    :class:`T1Decision` still forces a verifier + risk-gate pass
    before any reuse can drive execution (P2 backlog). Only reachable
    when ``t1_engine`` is wired in."""

    T1_ABSTAINED = "t1_abstained"
    """T0 abstained and T1 also abstained (no neighbour, or the best
    neighbour fell below the similarity / success-rate threshold).
    Only reachable when ``t1_engine`` is wired in - otherwise the
    caller sees :attr:`ABSTAINED_T0` and ``t1_decision`` is ``None``."""

    T2_PROPOSED_LOGGED = "t2_proposed_logged"
    """T0 (and T1, if wired) abstained; the T2 tier proposed a candidate
    that cleared the quality gate (mixed-model cross-check + verifier +
    grounding). Shadow-only in this wiring: the eligible candidate is
    recorded on the audit trail but does NOT execute - building an
    :class:`Action` from the candidate and routing it through the
    risk-gate is a separate step (P2/P3 backlog), mirroring the
    shadow-only :attr:`T1_REUSE_LOGGED`. Only reachable when ``t2_engine``
    is wired in."""

    T2_ESCALATED = "t2_escalated"
    """The T2 quality gate abstained or the mixed-model cross-check
    disagreed; the case escalates to HIL. Logged only in this wiring.
    Only reachable when ``t2_engine`` is wired in."""

    T2_DENIED = "t2_denied"
    """The T2 quality gate's verifier explicitly rejected the candidate;
    no execution. Only reachable when ``t2_engine`` is wired in."""

    T2_ABSTAINED = "t2_abstained"
    """The T2 proposer produced no candidate (nothing to gate). Only
    reachable when ``t2_engine`` is wired in."""


@dataclass(frozen=True, slots=True)
class ControlLoopResult:
    """Aggregate result for one event.

    ``decision`` follows the audit vocabulary defined in
    ``docs/roadmap/llm-strategy.md``:

    - ``auto`` - T0 matched and an action was executed (shadow PR opened).
    - ``abstain`` - routing or T0 abstained.
    - ``dedupe`` - duplicate delivery.

    ``hil`` and ``deny`` are Phase 2 risk-gate outputs and are not
    produced by the P1 loop.
    """

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
    """When the event was routed through the out-of-band detector, the
    detector's classification is surfaced here so a monitor / test can
    assert on it without inspecting the audit log."""

    t1_decision: T1Decision | None = None
    """When ``t1_engine`` was wired AND T0 abstained, the T1 tier is
    consulted and its decision (``REUSED`` or ``ABSTAIN``) is surfaced
    here so tests and observability can assert on the similarity
    outcome without walking the audit chain. ``None`` means the T1
    engine was not consulted for this event."""

    t2_decision: T2Decision | None = None
    """When ``t2_engine`` was wired AND T0 (and T1, if wired) abstained,
    the T2 tier is consulted and its decision (``PROPOSED`` / ``ESCALATE``
    / ``DENIED`` / ``ABSTAIN``) is surfaced here. ``None`` means the T2
    engine was not consulted for this event."""


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
        workflow_coordinator: WorkflowTriggerCoordinator | None = None,
    ) -> None:
        self._event_ingest = event_ingest
        self._trust_router = trust_router
        self._t0_engine = t0_engine
        self._action_builder = action_builder
        self._executor = executor
        self._audit_store = audit_store
        self._rules_by_id = dict(rules_by_id)
        self._change_safety_detector = change_safety_detector
        # Optional Axis-A table + ActionType map. When both are supplied the
        # loop records a shadow-parallel execution-authority decision on the
        # audit log for every executed action (judge-and-log only; it never
        # changes the executor path). Absent -> the loop behaves exactly as
        # before (regression-free). When ``risk_gate`` is ALSO supplied, the
        # record is the unified gate x authority decision (evaluator.combine).
        self._risk_table = risk_table
        self._action_types_by_name = (
            dict(action_types_by_name) if action_types_by_name is not None else {}
        )
        self._risk_gate = risk_gate
        # Optional Cost Governance vertical hook (Wave W2.5). Consulted
        # ONLY when the rule declares no static cost, so it never
        # overrides an authoritative rule figure; a None estimator
        # keeps the loop backward-compatible.
        self._cost_estimator = cost_estimator
        # Optional direct-API executor sibling (Wave W2.3 composition
        # wire). When wired, actions whose ActionType declares
        # ``execution_path == direct_api`` route to this executor
        # instead of the PR-native ShadowExecutor. Absent -> the loop
        # dispatches every action through ``self._executor`` exactly
        # as before, so composing without a direct-API adapter is a
        # supported (and default) configuration.
        self._direct_api_executor = direct_api_executor
        # Optional tool-call executor sibling (tool_call execution path).
        # When wired, actions whose ActionType declares
        # ``execution_path == tool_call`` route to this executor - it
        # invokes a registered function (generate a PDF, send a
        # notification, ...) rather than opening a PR or mutating a
        # substrate. Absent -> such actions fall through to the
        # PR-native path, so composing without a tool adapter is a
        # supported (and default) configuration.
        self._tool_executor = tool_executor
        # Optional T1 similarity tier (scope-expansion.md § 3.7). When
        # wired, T0 abstains fall through to T1 for a similarity /
        # learned-action reuse *log* (shadow-only in P1 - the
        # ``requires_reverification=True`` invariant on
        # :class:`T1Decision` forces a verifier + risk-gate pass
        # before any reuse can drive execution, wired in P2). Absent
        # keeps the loop backward-compatible: T0 abstain returns
        # :attr:`ABSTAINED_T0` and ``t1_decision`` is ``None``.
        self._t1_engine = t1_engine
        # Optional T2 reasoning tier (scope-expansion.md § 3.7). When
        # wired, an event that T0 (and T1, if wired) abstained on falls
        # through to T2: the injected T2Proposer proposes a candidate and
        # the existing QualityGate (mixed-model cross-check + verifier +
        # grounding) judges it. Shadow-only in this wiring - every T2
        # verdict is audited but nothing executes (building an Action
        # from the eligible candidate + routing it through the risk-gate
        # is a separate P2/P3 step, mirroring the shadow-only T1 reuse).
        # Absent keeps the loop backward-compatible.
        self._t2_engine = t2_engine
        # emits one :class:`StageEvent` at every observable stage
        # transition (``ingest``, ``route``, ``verify``, ``gate``,
        # ``execute``, ``audit``). The default
        # :class:`NullStagePublisher` discards - preserving the
        # backward-compatible no-observation behaviour. A composition
        # root that wants live observability binds
        # :class:`~fdai.shared.streaming.stage_publisher.SseSinkStagePublisher`
        # (in-process) or
        # :class:`~fdai.shared.streaming.stage_publisher.EventBusStagePublisher`
        # (multi-replica via Kafka + broadcaster).
        self._stage_publisher: StagePublisher = stage_publisher or NullStagePublisher()
        # Optional A2 operational-alert push (Notify-on-decision). When
        # wired, the loop dispatches one outbound, informational alert
        # per terminal decision (executed / hil / denied) through the
        # notification router. Absent -> no push (backward-compatible).
        # Push is best-effort: a delivery failure NEVER invalidates the
        # already-audited control decision (the router itself fails
        # toward safety by escalating to its HIL sink).
        self._notification_router = notification_router
        # Optional HIL approval round-trip coordinator (Notify-on-decision
        # step B). When wired, an action the risk gate routes to HIL is
        # parked and an A1 approval card is dispatched instead of the
        # decision ending at a bare audit row. Absent -> the loop records
        # the HIL decision and stops there (backward-compatible; the
        # action simply awaits a pull-side approve_hil). Parking is
        # best-effort at the loop boundary: a park/push failure is logged
        # and never turns a HIL verdict into an execution.
        self._hil_resume_coordinator = hil_resume_coordinator
        # Optional RCA coordinator (observability-and-detection.md 4).
        # When wired, each T0 finding gets a deterministic root-cause
        # hypothesis appended to the audit trail (the "why" behind the
        # decision). It never changes the executor path - RCA answers
        # "why", the risk gate answers "execute". Absent -> no RCA audit
        # (backward-compatible). Best-effort: an RCA failure never blocks
        # the control decision.
        self._rca_coordinator = rca_coordinator
        # Optional event correlator (observability-and-detection.md 1).
        # When wired, each event is anchored to a deterministic incident
        # id (correlation key + time window) so the RCA audit ties the
        # findings of one incident together. Absent -> no incident id on
        # the RCA audit (backward-compatible).
        self._event_correlator = event_correlator
        # Optional workflow trigger coordinator (process-automation.md 4).
        # When wired, every ingested event is also matched against the
        # Workflow trigger index and every matched Workflow runs in shadow
        # (structurally non-mutating). It is a pure side-consumer: it adds
        # audit rows and never changes the primary control decision or the
        # return path. Absent -> no workflows fire (backward-compatible).
        # Best-effort at the loop boundary: a coordinator failure is logged
        # and never breaks the control decision.
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
            detail={"event_type": event.event_type},
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

            # 3a. Optional T1 similarity fallback. When wired, T0
            # abstains fall through to T1 for a learned-action reuse
            # *log* (shadow-only in P1; the reuse never executes here
            # because :attr:`T1Decision.requires_reverification` MUST
            # gate through the verifier + risk-gate first, which lands
            # in P2). This preserves the deterministic-first principle
            # (T0 is authoritative when it matches) while giving T1
            # observability into which abstains would have been
            # reusable.
            t1_decision: T1Decision | None = None
            if self._t1_engine is not None:
                t1_decision = await self._t1_engine.evaluate(event=event)
                # verify.done for T1 - captures the similarity outcome.
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
                await self._write_t1_audit(
                    event=event,
                    decision=decision,
                    t1=t1_decision,
                )
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
                        reason="t1_reuse_shadow_only_p1",
                        event_id=str(event.event_id),
                        change_safety_decision=cs_decision,
                        t1_decision=t1_decision,
                    )
                if (
                    t2_result := await self._consult_t2(
                        event=event,
                        decision=decision,
                        citing=citing,
                        cs_decision=cs_decision,
                        t1_decision=t1_decision,
                        event_id=event_id,
                        correlation_id=correlation_id,
                    )
                ) is not None:
                    return t2_result
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
                    event_id=str(event.event_id),
                    change_safety_decision=cs_decision,
                    t1_decision=t1_decision,
                )

            if (
                t2_result := await self._consult_t2(
                    event=event,
                    decision=decision,
                    citing=citing,
                    cs_decision=cs_decision,
                    t1_decision=None,
                    event_id=event_id,
                    correlation_id=correlation_id,
                )
            ) is not None:
                return t2_result
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
                "mode": Mode.SHADOW.value,
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
            detail={"outcome": overall.value, "decision": decision_word},
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

    # ------------------------------------------------------------------
    # notification helper (A2 operational-alert, Notify-on-decision)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # HIL approval round-trip (Notify-on-decision step B)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # RCA helper (deterministic T0 root-cause -> audit)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # stage-publisher helper
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # audit helper
    # ------------------------------------------------------------------

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
        ``docs/roadmap/execution-model.md § 2.8``.
        """

        if rule.remediation.cost_impact_monthly_usd is not None:
            return None  # rule value is authoritative; do not override
        if self._cost_estimator is None:
            return None
        return await resolve_cost_impact_monthly(self._cost_estimator, action_type, arguments=None)

    async def _dispatch_action(
        self, *, action: Action, rule: Rule
    ) -> ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult:
        """Route ``action`` to the PR-native or direct-API executor.

        Selection rule (Wave W2.3 composition wire):

        - When the ActionType's ``execution_path`` is
          :attr:`ExecutionPath.DIRECT_API` AND a direct-API executor is
          wired -> :class:`DirectApiShadowExecutor`.
        - Otherwise -> the PR-native :class:`ShadowExecutor`.

        The default (``self._direct_api_executor is None``) keeps every
        action on the PR-native path so a composition that has no
        substrate adapter still functions - this matches the P1 upstream
        behaviour. A wired direct-API executor whose ActionType map
        does not classify the action as ``direct_api`` also falls
        through to the PR path; only ActionTypes that opt in via the
        ontology reach the direct-API sibling.
        """

        if self._direct_api_executor is not None:
            action_type = self._action_types_by_name.get(action.action_type)
            if action_type is not None and action_type.execution_path is ExecutionPath.DIRECT_API:
                return await self._direct_api_executor.execute(action=action)
        if self._tool_executor is not None:
            action_type = self._action_types_by_name.get(action.action_type)
            if action_type is not None and action_type.execution_path is ExecutionPath.TOOL_CALL:
                return await self._tool_executor.execute(action=action)
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
        t2_decision = await self._t2_engine.evaluate(event=event)
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
        outcome = _T2_OUTCOME_MAP[t2_decision.outcome]
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.AUDIT,
            phase=StagePhase.DONE,
            detail={"outcome": outcome.value},
        )
        return ControlLoopResult(
            outcome=outcome,
            tier="t2",
            decision="abstain",
            resource_type=decision.resource_type,
            citing_rule_ids=citing,
            reason=t2_decision.reason,
            event_id=str(event.event_id),
            change_safety_decision=cs_decision,
            t1_decision=t1_decision,
            t2_decision=t2_decision,
        )

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
            quality_summary = {
                "quality_outcome": t2.quality_decision.outcome.value,
                "grounded_rule_ids": list(t2.quality_decision.grounded_rule_ids),
                "aggregate_confidence": t2.quality_decision.aggregate_confidence,
                "reasons": list(t2.quality_decision.reasons),
            }
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
        cost_override = await self._resolve_cost_override(rule=rule, action_type=action_type)
        if self._risk_gate is not None:
            unified = evaluate_unified(
                event=event,
                action=action,
                rule=rule,
                action_type=action_type,
                table=self._risk_table,
                risk_gate=self._risk_gate,
                cost_override=cost_override,
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
        )
        entry["recorded_at"] = datetime.now(tz=UTC).isoformat()
        await self._audit_store.append_audit_entry(entry)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_environment(resource_props: Mapping[str, Any]) -> str:
    """Environment word for the risk table (risk-classification.md).

    ``prod`` / ``production`` -> ``prod``; ``non-prod`` / ``dev`` /
    ``test`` / ``staging`` / ``qa`` -> ``non-prod``; a missing or
    unrecognized value -> ``prod`` (fail-safe: unknown env is treated as
    the highest-risk category).
    """
    raw: Any = None
    tags = resource_props.get("tags")
    if isinstance(tags, dict):
        raw = tags.get("environment") or tags.get("Environment")
    if raw is None:
        raw = resource_props.get("environment")
    if not isinstance(raw, str):
        return "prod"
    value = raw.strip().lower()
    if value in {"prod", "production"}:
        return "prod"
    if value in {"non-prod", "nonprod", "dev", "test", "staging", "qa"}:
        return "non-prod"
    return "prod"


def _compute_authority(
    *,
    event: Event,
    rule: Rule,
    action_type: OntologyActionType,
    table: RiskTable,
    cost_override: float | None = None,
) -> ExecutionAuthorityDecision:
    """Run the execution-authority pipeline for one action + event context.

    Rule-fired actions run under the executor's Managed Identity, whose
    role is fixed at composition time (execution-model.md 2.5). Until
    the composition root plumbs a principal_role through the loop, the
    default is OWNER-equivalent - the MI holds the executor allowlist,
    which is the safety envelope; ActionType ceilings apply within it.
    A future PR passes the composition-time role through and drops
    this default.

    ``cost_override`` is used ahead of ``rule.remediation.cost_impact_monthly_usd``
    when supplied - this is the hook the Cost Governance
    :class:`~fdai.shared.providers.cost_estimator.CostEstimator`
    plumbs a dynamic estimate through (Wave W2.5). ``None`` means "no
    override", not "known-zero".
    """
    environment = _extract_environment(_extract_resource_props(event.payload))
    cost = cost_override if cost_override is not None else rule.remediation.cost_impact_monthly_usd
    return evaluate_execution_authority(
        tier=Tier.T0,
        action_type=action_type,
        table=table,
        principal_role=CeilingRole.OWNER,
        environment=environment,
        cost_impact_monthly=cost,
    )


def build_shadow_authority_audit(
    *,
    event: Event,
    action: Action,
    rule: Rule,
    action_type: OntologyActionType,
    table: RiskTable,
    cost_override: float | None = None,
) -> dict[str, Any]:
    """Build the ``risk_gate.shadow_authority`` audit entry for one action.

    Pure: derives the environment from the event payload, runs the unified
    execution-authority pipeline, and returns the audit dict (the caller
    stamps ``recorded_at``). Used by :class:`ControlLoop` when a risk table
    is wired in but no RiskGate is (authority-only record).

    ``cost_override`` (Wave W2.5) is forwarded to
    :func:`_compute_authority`; it wins over ``rule.remediation.cost_impact_monthly_usd``
    when set, matching the estimator-fallback contract on
    :class:`ControlLoop`.
    """
    decision = _compute_authority(
        event=event,
        rule=rule,
        action_type=action_type,
        table=table,
        cost_override=cost_override,
    )
    return {
        "event_id": str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "actor": "fdai.core.control_loop",
        "action_kind": "risk_gate.shadow_authority",
        "mode": Mode.SHADOW.value,
        "action_id": str(action.action_id),
        "action_type_id": action.action_type,
        **decision.as_audit_dict(),
    }


def evaluate_unified(
    *,
    event: Event,
    action: Action,
    rule: Rule,
    action_type: OntologyActionType,
    table: RiskTable,
    risk_gate: RiskGate,
    cost_override: float | None = None,
) -> UnifiedRiskDecision:
    """Run the runtime-Action gate and the policy-ceiling authority and
    combine them into a single :class:`UnifiedRiskDecision` (canonical-level
    ``min()``). Pure - no audit write, no I/O beyond the gate/authority
    reads.

    ``cost_override`` (Wave W2.5) plumbs a dynamic Cost Governance
    estimate into the authority side; when unset the authority path
    reads the static ``rule.remediation.cost_impact_monthly_usd`` as
    before.
    """
    gate_decision = risk_gate.evaluate(action=action, rule=rule, action_type=action_type)
    authority = _compute_authority(
        event=event,
        rule=rule,
        action_type=action_type,
        table=table,
        cost_override=cost_override,
    )
    return combine(gate_decision, authority)


def _unified_audit_dict(
    *, event: Event, action: Action, unified: UnifiedRiskDecision
) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "actor": "fdai.core.control_loop",
        "action_kind": "risk_gate.unified",
        "mode": Mode.SHADOW.value,
        "action_id": str(action.action_id),
        "action_type_id": action.action_type,
        **unified.as_audit_dict(),
    }


def build_unified_risk_audit(
    *,
    event: Event,
    action: Action,
    rule: Rule,
    action_type: OntologyActionType,
    table: RiskTable,
    risk_gate: RiskGate,
    cost_override: float | None = None,
) -> dict[str, Any]:
    """Build the ``risk_gate.unified`` audit entry combining gate + authority.

    Runs the runtime-Action gate (exemption / precondition / blast /
    promotion) and the policy-ceiling authority, then combines them into a
    single :class:`~fdai.core.risk_gate.evaluator.UnifiedRiskDecision`
    (canonical-level ``min()``). Judge-and-log only; the caller stamps
    ``recorded_at``.

    ``cost_override`` (Wave W2.5) forwards a Cost Governance estimate
    into :func:`evaluate_unified`; existing callers that omit it get the
    prior behaviour (rule's static cost only).
    """
    unified = evaluate_unified(
        event=event,
        action=action,
        rule=rule,
        action_type=action_type,
        table=table,
        risk_gate=risk_gate,
        cost_override=cost_override,
    )
    return _unified_audit_dict(event=event, action=action, unified=unified)


def _extract_resource_props(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Pull the resource ``props`` map out of the event payload.

    Two shapes are accepted (both documented in
    ``docs/roadmap/csp-neutrality.md § 5``):

    1. ``payload['resource']['props']`` - matches
       :class:`ResourceRecord` produced by the Inventory adapter.
    2. ``payload['props']`` - a legacy flat form used by some Phase 0
       fixture generators.
    """
    resource = payload.get("resource")
    if isinstance(resource, dict):
        props = resource.get("props")
        if isinstance(props, dict):
            return props
    flat = payload.get("props")
    if isinstance(flat, dict):
        return flat
    return {}


def _extract_resource_id(event: Event, decision: RoutingDecision) -> str:
    """Return a stable resource id derived from the event.

    Priority: ``payload.resource.resource_id`` → ``event.resource_ref``
    → a synthetic ``anonymous:<resource_type>`` fallback so T0 still
    has a non-empty key. The fallback is fine for tests + Phase 0
    scenarios that omit inventory correlation.
    """
    resource = event.payload.get("resource")
    if isinstance(resource, dict):
        rid = resource.get("resource_id")
        if isinstance(rid, str) and rid:
            return rid
    if event.resource_ref:
        return event.resource_ref
    return f"anonymous:{decision.resource_type or 'unknown'}"


def _is_execution_success(
    result: ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult | Any,
) -> bool:
    if not hasattr(result, "outcome"):
        return False
    return result.outcome in (
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
        DirectApiExecutionOutcome.DISPATCHED,
        DirectApiExecutionOutcome.ALREADY_APPLIED,
        ToolCallExecutionOutcome.DISPATCHED,
        ToolCallExecutionOutcome.ALREADY_APPLIED,
    )


def _synthetic_action_build_failure(*, event: Event, finding: Any, reason: str) -> ExecutionResult:
    """Return a synthetic :class:`ExecutionResult` for the caller.

    An :class:`ActionBuildError` means the executor was never invoked;
    the caller still expects a per-finding result, so we synthesize one
    with the ``rejected_invariant`` outcome and the reason on it.
    """
    return ExecutionResult(
        action_id=f"unbuilt::{event.idempotency_key}::{finding.rule_id}",
        outcome=ExecutorOutcome.REJECTED_INVARIANT,
        mode=Mode.SHADOW,
        pr_ref=None,
        pr_url=None,
        reason=reason,
    )


__all__ = [
    "ControlLoop",
    "ControlLoopOutcome",
    "ControlLoopResult",
]
