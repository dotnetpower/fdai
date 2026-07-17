"""Primary event-processing sequence for :class:`ControlLoop`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.control_loop._helpers import (
    _extract_resource_id,
    _extract_resource_props,
    _is_execution_success,
    _synthetic_action_build_failure,
)
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.control_loop.operator_request import process_operator_request
from fdai.core.executor import ExecutionResult
from fdai.core.executor.action_builder import ActionBuildError
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.core.trust_router import RoutingTier
from fdai.core.verticals.change_safety.detector import ChangeSafetyDecision
from fdai.rule_catalog.schema.effect import Effect, Enforcement
from fdai.shared.contracts.models import Event
from fdai.shared.providers.stage_publisher import StageName, StagePhase


async def process_event(host: Any, raw_event: Event | Mapping[str, Any]) -> ControlLoopResult:
    """Run one event through the ordered control-loop stages."""
    event = host._event_ingest.ingest(raw_event)
    if event is None:
        return ControlLoopResult(
            outcome=ControlLoopOutcome.DEDUPED,
            tier="abstain",
            decision="dedupe",
            resource_type=None,
            reason="duplicate_idempotency_key",
        )

    event_id = str(event.event_id)
    correlation_id = event.correlation_id or event_id
    incident_id = host._correlate_incident_id(event)

    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.INGEST,
        phase=StagePhase.DONE,
        detail={"event_type": event.event_type, "mode": event.mode.value},
    )
    await host._maybe_fire_workflows(event)

    if event.event_type == "operator_request":
        return await process_operator_request(
            host, event=event, event_id=event_id, correlation_id=correlation_id
        )

    cs_decision: ChangeSafetyDecision | None = None
    if host._change_safety_detector is not None and host._change_safety_detector.is_activity_log(
        event
    ):
        cs_decision = await host._change_safety_detector.detect(event)

    decision = host._trust_router.route(event)
    if decision.tier is RoutingTier.ABSTAIN:
        await host._emit_stage(
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
        await host._write_abstain_audit(
            event=event,
            decision=decision,
            reason=decision.reason or "trust_router_abstain",
            stage="trust_router",
        )
        await host._emit_stage(
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
        raise RuntimeError("trust router returned T0 without a resource_type")

    await host._emit_stage(
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
        await host._write_abstain_audit(
            event=event,
            decision=decision,
            reason=decision.reason or "no_rule_matches_resource_type",
            stage="trust_router",
        )
        fallback = await host._evaluate_fallback_tiers(
            event=event,
            decision=decision,
            citing=(),
            cs_decision=cs_decision,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        if fallback is not None:
            return fallback
        await host._emit_stage(
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

    resource_props = _extract_resource_props(event.payload)
    resource_id = _extract_resource_id(event, decision)
    verdict = host._t0_engine.evaluate(
        event_id=str(event.event_id),
        signal_id=str(event.event_id),
        resource_id=resource_id,
        resource_type=decision.resource_type,
        resource_props=resource_props,
        signal_type=event.event_type,
    )
    citing = verdict.audit_hint.citing_rule_ids if verdict.audit_hint else ()
    await host._emit_stage(
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
        await host._write_abstain_audit(
            event=event,
            decision=decision,
            reason=(
                verdict.audit_hint.reason
                if verdict.audit_hint and verdict.audit_hint.reason
                else "t0_no_match"
            ),
            stage="t0_evaluate",
        )
        await host._analyze_t2_rca_on_abstain(
            event=event, decision=decision, incident_id=incident_id
        )
        fallback = await host._evaluate_fallback_tiers(
            event=event,
            decision=decision,
            citing=citing,
            cs_decision=cs_decision,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        if fallback is not None:
            return fallback
        await host._emit_stage(
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

    await host._analyze_and_audit_t1_causal_chain(event=event, incident_id=incident_id)

    exec_results: list[ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult] = []
    routed: list[str] = []
    for finding in verdict.findings:
        rule = host._rules_by_id.get(finding.rule_id)
        if rule is None:  # pragma: no cover - index/catalog inconsistency
            raise KeyError(
                f"rule {finding.rule_id!r} appears in T0 findings but is not in the rules_by_id map"
            )
        assignment = host._resolve_governance_assignment(
            event=event,
            resource_id=finding.resource_id,
            resource_type=decision.resource_type,
            rule_id=rule.id,
        )
        if assignment is not None:
            await host._write_governance_assignment_audit(
                event=event,
                resource_id=finding.resource_id,
                resolution=assignment,
            )
            if assignment.parameter_tie:
                routed.append("hil")
                continue
            if assignment.effective_effect is Effect.DENY:
                routed.append("deny" if assignment.enforcement is Enforcement.ENFORCE else "hil")
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
        await host._analyze_and_audit_rca(
            event=event,
            finding=finding,
            rule=rule,
            resource_type=decision.resource_type,
            incident_id=incident_id,
        )
        try:
            action = host._action_builder.build_from_finding(
                event=event, finding=finding, rule=rule
            )
        except ActionBuildError as exc:
            await host._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.GATE,
                phase=StagePhase.FAILED,
                detail={"rule_id": finding.rule_id, "stage": "action_build"},
                error=str(exc),
            )
            await host._write_abstain_audit(
                event=event,
                decision=decision,
                reason=str(exc),
                stage="action_build",
            )
            exec_results.append(
                _synthetic_action_build_failure(event=event, finding=finding, reason=str(exc))
            )
            continue

        unified = await host._evaluate_and_audit(event=event, action=action, rule=rule)
        gate_decision = (
            "deny"
            if unified is not None and unified.is_denied
            else "hil"
            if unified is not None and unified.requires_hil
            else "auto"
        )
        await host._emit_stage(
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
            routed.append("deny" if unified.is_denied else "hil")
            if (
                unified.requires_hil
                and not unified.is_denied
                and host._hil_resume_coordinator is not None
            ):
                await host._request_hil_approval(
                    action=action,
                    rule=rule,
                    correlation_id=correlation_id,
                )
            continue
        result = await host._dispatch_action(action=action, rule=rule)
        exec_results.append(result)
        exec_success = _is_execution_success(result)
        exec_stage_detail: dict[str, Any] = {
            "rule_id": finding.rule_id,
            "action_type": action.action_type,
            "mode": action.mode.value,
        }
        if exec_success:
            await host._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.EXECUTE,
                phase=StagePhase.DONE,
                detail=exec_stage_detail,
            )
        else:
            await host._emit_stage(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=StageName.EXECUTE,
                phase=StagePhase.FAILED,
                detail=exec_stage_detail,
                error=getattr(result, "reason", None) or "execution_failed",
            )

    if "deny" in routed:
        overall = ControlLoopOutcome.DENIED
    elif "hil" in routed:
        overall = ControlLoopOutcome.HIL
    elif any(_is_execution_success(result) for result in exec_results):
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
    await host._emit_stage(
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
    await host._notify_decision(
        event=event,
        correlation_id=correlation_id,
        overall=overall,
        decision_word=decision_word,
        resource_type=decision.resource_type,
        citing_rule_ids=tuple(finding.rule_id for finding in verdict.findings),
    )
    return ControlLoopResult(
        outcome=overall,
        tier="t0",
        decision=decision_word,
        resource_type=decision.resource_type,
        citing_rule_ids=tuple(finding.rule_id for finding in verdict.findings),
        execution_results=tuple(exec_results),
        event_id=str(event.event_id),
        change_safety_decision=cs_decision,
    )


__all__ = ["process_event"]
