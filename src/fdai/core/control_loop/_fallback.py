"""T1 and T2 fallback orchestration after deterministic abstention."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

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
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.state_store import StateStore

_T2_OUTCOME_MAP: Mapping[T2Outcome, ControlLoopOutcome] = {
    T2Outcome.PROPOSED: ControlLoopOutcome.T2_PROPOSED_LOGGED,
    T2Outcome.ESCALATE: ControlLoopOutcome.T2_ESCALATED,
    T2Outcome.DENIED: ControlLoopOutcome.T2_DENIED,
    T2Outcome.ABSTAIN: ControlLoopOutcome.T2_ABSTAINED,
}


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

    async def _emit_stage(self, **kwargs: object) -> None: ...

    async def _evaluate_and_audit(
        self, *, event: Event, action: Action, rule: Rule
    ) -> UnifiedRiskDecision | None: ...

    async def _request_hil_approval(
        self, *, action: Action, rule: Rule, correlation_id: str
    ) -> None: ...

    async def _write_t1_audit(
        self, *, event: Event, decision: RoutingDecision, t1: T1Decision
    ) -> None: ...

    async def _write_t2_audit(
        self, *, event: Event, decision: RoutingDecision, t2: T2Decision
    ) -> None: ...

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
        return None


__all__ = ["ControlLoopFallbackMixin"]
