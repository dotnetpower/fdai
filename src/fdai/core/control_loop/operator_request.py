"""Authoritative processing for normalized operator ActionProposals."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.control_loop._helpers import _is_execution_success
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.executor import ExecutionResult
from fdai.core.executor.action_builder import ActionBuilder, ActionBuildError
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)
ExecutionResultType = ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult


class OperatorRequestHost(Protocol):
    """ControlLoop capabilities used by the operator-request processor."""

    _action_builder: ActionBuilder
    _audit_store: StateStore
    _hil_resume_coordinator: HilResumeCoordinator | None
    _inventory_context_provider: Callable[[str], Awaitable[Mapping[str, Any] | None]] | None

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

    async def _dispatch_action(self, *, action: Action, rule: Rule) -> ExecutionResultType: ...

    async def _request_hil_approval(
        self,
        *,
        action: Action,
        rule: Rule,
        correlation_id: str,
        submitter_oid: str,
    ) -> None: ...

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


async def process_operator_request(
    host: OperatorRequestHost,
    *,
    event: Event,
    event_id: str,
    correlation_id: str,
) -> ControlLoopResult:
    """Validate and govern one normalized operator-initiated proposal."""
    event = await _enrich_from_inventory(host, event=event, event_id=event_id)
    request = event.payload.get("operator_request")
    initiator = request.get("initiator_principal") if isinstance(request, dict) else None
    resource = event.payload.get("resource")
    resource_type_value = resource.get("resource_type") if isinstance(resource, dict) else None
    resource_type = (
        resource_type_value if isinstance(resource_type_value, str) else "operator-request"
    )
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.ROUTE,
        phase=StagePhase.DONE,
        detail={"routed_to": "t0", "resource_type": resource_type},
    )
    try:
        action, rule = host._action_builder.build_from_operator_request(event=event)
    except ActionBuildError as exc:
        await _audit_abstain(host, event=event, reason=str(exc))
        return await _finish(
            host,
            event=event,
            correlation_id=correlation_id,
            outcome=ControlLoopOutcome.ABSTAINED_ACTION_BUILD,
            decision="abstain",
            resource_type=resource_type,
            reason="operator_request_action_build_failed",
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
            reason=reason,
        )

    if unified.is_auto or unified.requires_hil:
        action = action.model_copy(update={"mode": unified.gate.effective_mode})
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.GATE,
        phase=StagePhase.DONE,
        detail={
            "tier": "t0",
            "action_type": action.action_type,
            "gate_decision": unified.decision,
            "mode": action.mode.value,
        },
    )
    if unified.is_denied:
        return await _finish_terminal(
            host, event, correlation_id, resource_type, rule, ControlLoopOutcome.DENIED, "deny"
        )
    if unified.requires_hil:
        if host._hil_resume_coordinator is not None and isinstance(initiator, str):
            await host._request_hil_approval(
                action=action,
                rule=rule,
                correlation_id=correlation_id,
                submitter_oid=initiator,
            )
        return await _finish_terminal(
            host, event, correlation_id, resource_type, rule, ControlLoopOutcome.HIL, "hil"
        )
    if not unified.is_auto:
        return await _finish_terminal(
            host,
            event,
            correlation_id,
            resource_type,
            rule,
            ControlLoopOutcome.OPERATOR_REQUEST_LOGGED,
            "shadow",
        )

    result = await host._dispatch_action(action=action, rule=rule)
    succeeded = _is_execution_success(result)
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.EXECUTE,
        phase=StagePhase.DONE if succeeded else StagePhase.FAILED,
        detail={"action_type": action.action_type, "mode": action.mode.value},
        error=None if succeeded else getattr(result, "reason", None) or "execution_failed",
    )
    return await _finish(
        host,
        event=event,
        correlation_id=correlation_id,
        outcome=(
            ControlLoopOutcome.EXECUTED if succeeded else ControlLoopOutcome.ABSTAINED_ACTION_BUILD
        ),
        decision="auto" if succeeded else "abstain",
        resource_type=resource_type,
        citing_rule_ids=(rule.id,),
        execution_results=(result,),
    )


async def _enrich_from_inventory(
    host: OperatorRequestHost, *, event: Event, event_id: str
) -> Event:
    if host._inventory_context_provider is None or not event.resource_ref:
        return event
    try:
        inventory_resource = await host._inventory_context_provider(event.resource_ref)
    except Exception:  # noqa: BLE001 - inventory lookup fails closed
        _LOGGER.warning(
            "operator_request_inventory_context_failed",
            extra={"event_id": event_id},
            exc_info=True,
        )
        return event
    if inventory_resource is None:
        return event
    return event.model_copy(
        update={"payload": {**event.payload, "resource": dict(inventory_resource)}}
    )


async def _audit_abstain(host: OperatorRequestHost, *, event: Event, reason: str) -> None:
    await host._audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Heimdall",
            "action_kind": "control_loop.operator_request_abstain",
            "mode": Mode.SHADOW.value,
            "reason": reason,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
    )


async def _finish_terminal(
    host: OperatorRequestHost,
    event: Event,
    correlation_id: str,
    resource_type: str,
    rule: Rule,
    outcome: ControlLoopOutcome,
    decision: str,
) -> ControlLoopResult:
    return await _finish(
        host,
        event=event,
        correlation_id=correlation_id,
        outcome=outcome,
        decision=decision,
        resource_type=resource_type,
        citing_rule_ids=(rule.id,),
    )


async def _finish(
    host: OperatorRequestHost,
    *,
    event: Event,
    correlation_id: str,
    outcome: ControlLoopOutcome,
    decision: str,
    resource_type: str,
    citing_rule_ids: tuple[str, ...] = (),
    execution_results: tuple[ExecutionResultType, ...] = (),
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
            "mode": event.mode.value,
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
        execution_results=execution_results,
        reason=reason,
        event_id=str(event.event_id),
    )


__all__ = ["OperatorRequestHost", "process_operator_request"]
