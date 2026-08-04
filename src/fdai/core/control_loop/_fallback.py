"""T1 and T2 fallback orchestration after deterministic abstention."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.assurance_twin import DynamicRuntimeCoordinator, GraphDynamicRuntimeCoordinator
from fdai.core.control_loop._helpers import _is_execution_success
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.executor.action_builder import ActionBuilder, ActionBuildError
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.core.tiers.t1_lightweight.tier import T1Decision, T1Outcome, T1Tier
from fdai.core.tiers.t2_reasoning import T2Decision, T2Outcome, T2ProposalContext, T2Tier
from fdai.core.trust_router import RoutingDecision
from fdai.core.verticals.change_safety.detector import ChangeSafetyDecision
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.execution_authorization import (
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
)
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.state_store import StateStore

_T2_OUTCOME_MAP: Mapping[T2Outcome, ControlLoopOutcome] = {
    T2Outcome.PROPOSED: ControlLoopOutcome.T2_PROPOSED_LOGGED,
    T2Outcome.ESCALATE: ControlLoopOutcome.T2_ESCALATED,
    T2Outcome.DENIED: ControlLoopOutcome.T2_DENIED,
    T2Outcome.ABSTAIN: ControlLoopOutcome.T2_ABSTAINED,
}
_LOGGER = logging.getLogger("fdai.core.control_loop.fallback")


@dataclass(frozen=True, slots=True)
class DynamicGuardDecision:
    configured: bool
    passed: bool
    reasons: tuple[str, ...] = ()


class ControlLoopFallbackMixin:
    """Run shadow-only T1/T2 fallback stages and route T2 candidates."""

    _action_builder: ActionBuilder
    _audit_store: StateStore
    _hil_resume_coordinator: HilResumeCoordinator | None
    _risk_gate: RiskGate | None
    _risk_table: RiskTable | None
    _rules_by_id: Mapping[str, Rule]
    _t1_engine: T1Tier | None
    _t2_engine: T2Tier | None
    _dynamic_runtime_coordinator: DynamicRuntimeCoordinator | None
    _graph_dynamic_runtime_coordinator: GraphDynamicRuntimeCoordinator | None

    async def _emit_stage(
        self,
        *,
        event_id: str,
        correlation_id: str,
        stage: StageName,
        phase: StagePhase,
        detail: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> None: ...

    async def _evaluate_and_audit(
        self, *, event: Event, action: Action, rule: Rule
    ) -> UnifiedRiskDecision | None: ...

    async def _evaluate_execution_authorization(
        self,
        *,
        event: Event,
        action: Action,
    ) -> ExecutionAuthorizationResult | None: ...

    async def _dispatch_action(self, *, action: Action, rule: Rule) -> Any: ...

    def _bind_authorized_identity(
        self,
        action: Action,
        authorization: ExecutionAuthorizationResult | None,
    ) -> Action:
        raise NotImplementedError

    async def _request_hil_approval(
        self, *, action: Action, rule: Rule, correlation_id: str
    ) -> None: ...

    async def _write_t1_audit(
        self, *, event: Event, decision: RoutingDecision, t1: T1Decision
    ) -> None: ...

    async def _write_t2_audit(
        self, *, event: Event, decision: RoutingDecision, t2: T2Decision
    ) -> None: ...

    async def _simulate_and_audit_dynamic(
        self,
        *,
        event: Event,
        t1: T1Decision,
    ) -> DynamicGuardDecision:
        coordinator = self._dynamic_runtime_coordinator
        if t1.best_match is None:
            return DynamicGuardDecision(False, True)
        if coordinator is None:
            return await self._simulate_and_audit_graph_dynamic(event=event, t1=t1)
        reasons: list[str] = []
        try:
            result = await coordinator.simulate(event=event, action=t1.best_match.action)
        except Exception as exc:  # noqa: BLE001 - fail closed into Dynamic hold
            simulation = None
            reason = f"simulation_failed:{type(exc).__name__}"
            reasons.append(reason)
        else:
            simulation = result.simulation
            reason = result.reason
            if simulation is None:
                reasons.append(reason)
            elif simulation.requires_review:
                reasons.append("scalar_simulation_requires_review")
        entry = {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": f"{event.idempotency_key}:dynamic_simulation",
            "actor": "fdai.core.assurance_twin",
            "action_kind": "dynamic.simulation",
            "mode": Mode.SHADOW.value,
            "simulation_reason": reason,
            "simulation_id": simulation.simulation_id if simulation else None,
            "simulation_requires_review": simulation.requires_review if simulation else True,
            "ordered_branch_ids": list(simulation.ordered_branch_ids) if simulation else [],
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            await self._audit_store.append_audit_entry(entry)
        except Exception:  # noqa: BLE001 - missing decision evidence must hold
            reasons.append("scalar_simulation_audit_failed")
            _LOGGER.warning(
                "dynamic_simulation_audit_failed",
                extra={
                    "event_id": str(event.event_id),
                    "simulation_reason": reason,
                },
                exc_info=True,
            )
        graph = await self._simulate_and_audit_graph_dynamic(event=event, t1=t1)
        reasons.extend(graph.reasons)
        normalized = tuple(sorted(set(reasons)))
        return DynamicGuardDecision(True, not normalized, normalized)

    async def _simulate_and_audit_graph_dynamic(
        self,
        *,
        event: Event,
        t1: T1Decision,
    ) -> DynamicGuardDecision:
        coordinator = self._graph_dynamic_runtime_coordinator
        if coordinator is None or t1.best_match is None:
            return DynamicGuardDecision(False, True)
        reasons: list[str] = []
        try:
            result = await coordinator.simulate(event=event, action=t1.best_match.action)
        except Exception as exc:  # noqa: BLE001 - fail closed into Dynamic hold
            simulation = None
            reason = f"graph_simulation_failed:{type(exc).__name__}"
            reasons.append(reason)
        else:
            simulation = result.simulation
            reason = result.reason
            if simulation is None:
                reasons.append(reason)
            elif simulation.requires_review:
                reasons.extend(simulation.reason_codes or ("graph_simulation_requires_review",))
        entry = {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": f"{event.idempotency_key}:graph_dynamic_simulation",
            "actor": "fdai.core.assurance_twin",
            "action_kind": "dynamic.graph_simulation",
            "mode": Mode.SHADOW.value,
            "simulation_reason": reason,
            "trajectory_digest": (
                simulation.active_trajectory.digest if simulation is not None else None
            ),
            "simulation_requires_review": (
                simulation.requires_review if simulation is not None else True
            ),
            "reason_codes": list(simulation.reason_codes) if simulation is not None else [],
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            await self._audit_store.append_audit_entry(entry)
        except Exception:  # noqa: BLE001 - missing decision evidence must hold
            reasons.append("graph_simulation_audit_failed")
            _LOGGER.warning(
                "graph_dynamic_simulation_audit_failed",
                extra={"event_id": str(event.event_id), "simulation_reason": reason},
                exc_info=True,
            )
        normalized = tuple(sorted(set(reasons)))
        return DynamicGuardDecision(True, not normalized, normalized)

    async def _routing_hold(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        tier: str,
        reason: str,
        citing_rule_ids: tuple[str, ...],
        cs_decision: ChangeSafetyDecision | None,
        t1_decision: T1Decision | None = None,
        t2_decision: T2Decision | None = None,
    ) -> ControlLoopResult:
        await self._audit_store.append_audit_entry(
            {
                "event_id": str(event.event_id),
                "correlation_id": event.correlation_id or str(event.event_id),
                "idempotency_key": event.idempotency_key,
                "actor": "fdai.core.control_loop",
                "producer_principal": "Forseti",
                "action_kind": f"control_loop.{tier}_routing_hold",
                "mode": Mode.SHADOW.value,
                "decision": "hil",
                "reason": reason,
                "citing_rule_ids": list(citing_rule_ids),
                "recorded_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        return ControlLoopResult(
            outcome=ControlLoopOutcome.HIL,
            tier=tier,
            decision="hil",
            resource_type=decision.resource_type,
            citing_rule_ids=citing_rule_ids,
            reason=reason,
            event_id=str(event.event_id),
            change_safety_decision=cs_decision,
            t1_decision=t1_decision,
            t2_decision=t2_decision,
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
                dynamic_guard = await self._simulate_and_audit_dynamic(
                    event=event,
                    t1=t1_decision,
                )
                if dynamic_guard.configured and not dynamic_guard.passed:
                    return await self._routing_hold(
                        event=event,
                        decision=decision,
                        tier="t1",
                        reason=f"dynamic_guard:{','.join(dynamic_guard.reasons)}",
                        citing_rule_ids=(
                            (t1_decision.best_match.action.rule_id,)
                            if t1_decision.best_match is not None
                            else citing
                        ),
                        cs_decision=cs_decision,
                        t1_decision=t1_decision,
                    )
                routed = await self._route_t1_reuse(
                    event=event,
                    decision=decision,
                    t1=t1_decision,
                    cs_decision=cs_decision,
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

    async def _route_t1_reuse(
        self,
        *,
        event: Event,
        decision: RoutingDecision,
        t1: T1Decision,
        cs_decision: ChangeSafetyDecision | None,
        event_id: str,
        correlation_id: str,
    ) -> ControlLoopResult | None:
        best_match = t1.best_match
        if best_match is None or t1.current_reuse_verification is None:
            return None
        learned = best_match.action
        rule = self._rules_by_id.get(learned.rule_id)
        if rule is None or rule.remediates != learned.action_type:
            reason = "t1_reuse_rule_missing" if rule is None else "t1_reuse_rule_action_mismatch"
            await self._audit_store.append_audit_entry(
                {
                    "event_id": event_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": event.idempotency_key,
                    "actor": "fdai.core.control_loop",
                    "producer_principal": "Forseti",
                    "action_kind": "control_loop.t1_action_build_abstain",
                    "mode": Mode.SHADOW.value,
                    "reason": reason,
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
            return ControlLoopResult(
                outcome=ControlLoopOutcome.ABSTAINED_ACTION_BUILD,
                tier="t1",
                decision="abstain",
                resource_type=decision.resource_type,
                citing_rule_ids=(learned.rule_id,),
                reason=reason,
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1,
            )
        target_resource_ref = _t1_target_resource_ref(event)
        try:
            action = self._action_builder.build_from_learned_action(
                event=event,
                learned=learned,
                target_resource_ref=target_resource_ref,
            )
        except ActionBuildError as exc:
            await self._audit_store.append_audit_entry(
                {
                    "event_id": event_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": event.idempotency_key,
                    "actor": "fdai.core.control_loop",
                    "producer_principal": "Forseti",
                    "action_kind": "control_loop.t1_action_build_abstain",
                    "mode": Mode.SHADOW.value,
                    "reason": str(exc),
                    "recorded_at": datetime.now(tz=UTC).isoformat(),
                }
            )
            return ControlLoopResult(
                outcome=ControlLoopOutcome.ABSTAINED_ACTION_BUILD,
                tier="t1",
                decision="abstain",
                resource_type=decision.resource_type,
                citing_rule_ids=(learned.rule_id,),
                reason="t1_reuse_action_build_failed",
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1,
            )

        authorization = await self._evaluate_execution_authorization(event=event, action=action)
        if authorization is not None and not authorization.can_enter_risk_gate:
            denied = authorization.status in {
                ExecutionAuthorizationStatus.PROHIBITED,
                ExecutionAuthorizationStatus.POLICY_CONFLICT,
                ExecutionAuthorizationStatus.UNCONFIGURED,
            }
            return ControlLoopResult(
                outcome=ControlLoopOutcome.DENIED if denied else ControlLoopOutcome.HIL,
                tier="t1",
                decision="deny" if denied else "hil",
                resource_type=decision.resource_type,
                citing_rule_ids=(learned.rule_id,),
                reason=f"execution_authorization:{authorization.status.value}",
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1,
            )
        action = self._bind_authorized_identity(action, authorization)

        unified = await self._evaluate_and_audit(event=event, action=action, rule=rule)
        if unified is None:
            return await self._routing_hold(
                event=event,
                decision=decision,
                tier="t1",
                reason="t1_risk_gate_unavailable",
                citing_rule_ids=(learned.rule_id,),
                cs_decision=cs_decision,
                t1_decision=t1,
            )
        if unified.is_auto or unified.requires_hil:
            action = action.model_copy(update={"mode": unified.gate.effective_mode})
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.GATE,
            phase=StagePhase.DONE,
            detail={
                "tier": "t1",
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
            return ControlLoopResult(
                outcome=(
                    ControlLoopOutcome.DENIED if unified.is_denied else ControlLoopOutcome.HIL
                ),
                tier="t1",
                decision="deny" if unified.is_denied else "hil",
                resource_type=decision.resource_type,
                citing_rule_ids=(learned.rule_id,),
                reason="t1_reuse_risk_gated",
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1,
            )
        if not unified.is_auto:
            return ControlLoopResult(
                outcome=ControlLoopOutcome.T1_REUSE_LOGGED,
                tier="t1",
                decision="shadow",
                resource_type=decision.resource_type,
                citing_rule_ids=(learned.rule_id,),
                reason="t1_reuse_verified_shadow",
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1,
            )

        execution = await self._dispatch_action(action=action, rule=rule)
        succeeded = _is_execution_success(execution)
        await self._emit_stage(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=StageName.EXECUTE,
            phase=StagePhase.DONE if succeeded else StagePhase.FAILED,
            detail={"tier": "t1", "action_type": action.action_type, "mode": action.mode.value},
            error=None if succeeded else getattr(execution, "reason", None),
        )
        return ControlLoopResult(
            outcome=(
                ControlLoopOutcome.EXECUTED
                if succeeded
                else ControlLoopOutcome.ABSTAINED_ACTION_BUILD
            ),
            tier="t1",
            decision="auto" if succeeded else "abstain",
            resource_type=decision.resource_type,
            citing_rule_ids=(learned.rule_id,),
            execution_results=(execution,),
            reason=None if succeeded else "t1_reuse_execution_failed",
            event_id=event_id,
            change_safety_decision=cs_decision,
            t1_decision=t1,
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
        if not allowed_rules:
            return None
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
        if candidate is None:
            return None
        if self._risk_table is None or self._risk_gate is None:
            return await self._routing_hold(
                event=event,
                decision=decision,
                tier="t2",
                reason="t2_risk_gate_unavailable",
                citing_rule_ids=candidate.cited_rule_ids,
                cs_decision=cs_decision,
                t1_decision=t1_decision,
                t2_decision=t2,
            )
        rule = next(
            (
                self._rules_by_id[rule_id]
                for rule_id in candidate.cited_rule_ids
                if rule_id in self._rules_by_id
            ),
            None,
        )
        if rule is None:
            return await self._routing_hold(
                event=event,
                decision=decision,
                tier="t2",
                reason="t2_cited_rule_unavailable",
                citing_rule_ids=candidate.cited_rule_ids,
                cs_decision=cs_decision,
                t1_decision=t1_decision,
                t2_decision=t2,
            )
        try:
            action = self._action_builder.build_from_candidate(event=event, candidate=candidate)
        except ActionBuildError as exc:
            await self._audit_store.append_audit_entry(
                {
                    "event_id": event_id,
                    "correlation_id": correlation_id,
                    "idempotency_key": event.idempotency_key,
                    "actor": "fdai.core.control_loop",
                    "producer_principal": "Forseti",
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

        authorization = await self._evaluate_execution_authorization(event=event, action=action)
        if authorization is not None and not authorization.can_enter_risk_gate:
            denied = authorization.status in {
                ExecutionAuthorizationStatus.PROHIBITED,
                ExecutionAuthorizationStatus.POLICY_CONFLICT,
                ExecutionAuthorizationStatus.UNCONFIGURED,
            }
            return ControlLoopResult(
                outcome=ControlLoopOutcome.DENIED if denied else ControlLoopOutcome.HIL,
                tier="t2",
                decision="deny" if denied else "hil",
                resource_type=decision.resource_type,
                citing_rule_ids=candidate.cited_rule_ids,
                reason=f"execution_authorization:{authorization.status.value}",
                event_id=event_id,
                change_safety_decision=cs_decision,
                t1_decision=t1_decision,
                t2_decision=t2,
            )
        action = self._bind_authorized_identity(action, authorization)

        unified = await self._evaluate_and_audit(event=event, action=action, rule=rule)
        if unified is None:
            return await self._routing_hold(
                event=event,
                decision=decision,
                tier="t2",
                reason="t2_risk_gate_unavailable",
                citing_rule_ids=candidate.cited_rule_ids,
                cs_decision=cs_decision,
                t1_decision=t1_decision,
                t2_decision=t2,
            )
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
        return None


def _t1_target_resource_ref(event: Event) -> str:
    if event.resource_ref:
        return event.resource_ref
    resource = event.payload.get("resource")
    if isinstance(resource, dict):
        for field in ("resource_id", "id"):
            value = resource.get(field)
            if isinstance(value, str) and value:
                return value
    return ""


__all__ = ["ControlLoopFallbackMixin"]
