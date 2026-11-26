"""Governed shadow processing for Operational Readiness remediation requests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.executor.action_builder import ActionBuilder, ActionBuildError
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.state_store import StateStore


class ReadinessRemediationHost(Protocol):
    """Control-loop capabilities used by the ORR shadow processor."""

    _action_builder: ActionBuilder
    _audit_store: StateStore

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

    async def _notify_decision(
        self,
        *,
        event: Event,
        correlation_id: str,
        overall: ControlLoopOutcome,
        decision_word: str,
        resource_type: str | None,
        citing_rule_ids: tuple[str, ...],
    ) -> None: ...


async def process_readiness_remediation(
    host: ReadinessRemediationHost,
    *,
    event: Event,
    event_id: str,
    correlation_id: str,
) -> ControlLoopResult:
    """Validate one ORR request, evaluate risk, and stop before execution authority."""

    resource = event.payload.get("resource")
    resource_type_value = resource.get("resource_type") if isinstance(resource, dict) else None
    resource_type = (
        resource_type_value if isinstance(resource_type_value, str) else "operational-readiness"
    )
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.ROUTE,
        phase=StagePhase.DONE,
        detail={"routed_to": "t0", "resource_type": resource_type},
    )
    try:
        action, rule = host._action_builder.build_from_readiness_remediation(event=event)
    except ActionBuildError as exc:
        await _audit_abstain(host, event=event, reason=str(exc))
        return await _finish(
            host,
            event=event,
            correlation_id=correlation_id,
            outcome=ControlLoopOutcome.ABSTAINED_ACTION_BUILD,
            decision="abstain",
            resource_type=resource_type,
            reason="readiness_remediation_action_build_failed",
        )
    unified = await host._evaluate_and_audit(event=event, action=action, rule=rule)
    if unified is None:
        reason = "unified_risk_gate_not_wired"
        await _audit_abstain(host, event=event, reason=reason)
        return await _finish(
            host,
            event=event,
            correlation_id=correlation_id,
            outcome=ControlLoopOutcome.ABSTAINED_ACTION_BUILD,
            decision="abstain",
            resource_type=resource_type,
            citing_rule_ids=tuple(action.citing_rules),
            reason=reason,
        )
    decision = "deny" if unified.is_denied else "hil" if unified.requires_hil else "shadow"
    outcome = (
        ControlLoopOutcome.DENIED
        if unified.is_denied
        else ControlLoopOutcome.HIL
        if unified.requires_hil
        else ControlLoopOutcome.READINESS_REMEDIATION_LOGGED
    )
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.GATE,
        phase=StagePhase.DONE,
        detail={
            "tier": "t0",
            "action_type": action.action_type,
            "gate_decision": unified.decision,
            "mode": Mode.SHADOW.value,
            "execution_authority": False,
        },
    )
    return await _finish(
        host,
        event=event,
        correlation_id=correlation_id,
        outcome=outcome,
        decision=decision,
        resource_type=resource_type,
        citing_rule_ids=tuple(action.citing_rules),
    )


async def _audit_abstain(
    host: ReadinessRemediationHost,
    *,
    event: Event,
    reason: str,
) -> None:
    await host._audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "operational_readiness",
            "action_kind": "control_loop.readiness_remediation_abstain",
            "mode": Mode.SHADOW.value,
            "execution_authority": False,
            "reason": reason,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
    )


async def _finish(
    host: ReadinessRemediationHost,
    *,
    event: Event,
    correlation_id: str,
    outcome: ControlLoopOutcome,
    decision: str,
    resource_type: str,
    citing_rule_ids: tuple[str, ...] = (),
    reason: str | None = None,
) -> ControlLoopResult:
    await host._emit_stage(
        event_id=str(event.event_id),
        correlation_id=correlation_id,
        stage=StageName.AUDIT,
        phase=StagePhase.DONE,
        detail={
            "outcome": outcome.value,
            "decision": decision,
            "gate_decision": decision,
            "mode": Mode.SHADOW.value,
            "execution_authority": False,
        },
    )
    await host._notify_decision(
        event=event,
        correlation_id=correlation_id,
        overall=outcome,
        decision_word=decision,
        resource_type=resource_type,
        citing_rule_ids=citing_rule_ids,
    )
    return ControlLoopResult(
        outcome=outcome,
        tier="t0",
        decision=decision,
        resource_type=resource_type,
        citing_rule_ids=citing_rule_ids,
        reason=reason,
        event_id=str(event.event_id),
    )


__all__ = ["ReadinessRemediationHost", "process_readiness_remediation"]
