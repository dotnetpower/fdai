"""Module-level helpers extracted from control_loop.py (G-2, tracker #14).

These are the small pure-function utilities that ``ControlLoop`` uses:
resource-property extraction, environment classification, unified-risk
authority computation, and audit-record shaping. Kept out of the class
so they stay independently testable and so the orchestrator file
shrinks to its class-only shape.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
)
from fdai.core.risk_gate.authority import (
    ExecutionAuthorityDecision,
    evaluate_execution_authority,
)
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision, combine
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import RiskTable
from fdai.core.trust_router import RoutingDecision
from fdai.shared.contracts.models import (
    Action,
    CeilingRole,
    Event,
    Mode,
    OntologyActionType,
    Rule,
    Tier,
)

_LOGGER = logging.getLogger(__name__)


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
        raw = tags.get("fdai:env") or tags.get("environment") or tags.get("Environment")
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
    system_degraded: bool = False,
    kill_switch_engaged: bool = False,
    inventory_age_seconds: int | None = None,
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
        system_degraded=system_degraded,
        kill_switch_engaged=kill_switch_engaged,
    )


def build_shadow_authority_audit(
    *,
    event: Event,
    action: Action,
    rule: Rule,
    action_type: OntologyActionType,
    table: RiskTable,
    cost_override: float | None = None,
    system_degraded: bool = False,
    kill_switch_engaged: bool = False,
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
        system_degraded=system_degraded,
        kill_switch_engaged=kill_switch_engaged,
    )
    return {
        "event_id": str(event.event_id),
        "correlation_id": event.correlation_id or str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "actor": "fdai.core.control_loop",
        "producer_principal": "Forseti",
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
    system_degraded: bool = False,
    kill_switch_engaged: bool = False,
    inventory_age_seconds: int | None = None,
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
    gate_decision = risk_gate.evaluate(
        action=action,
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=inventory_age_seconds,
    )
    authority = _compute_authority(
        event=event,
        rule=rule,
        action_type=action_type,
        table=table,
        cost_override=cost_override,
        system_degraded=system_degraded,
        kill_switch_engaged=kill_switch_engaged,
    )
    return combine(gate_decision, authority)


def _unified_audit_dict(
    *, event: Event, action: Action, unified: UnifiedRiskDecision
) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "correlation_id": event.correlation_id or str(event.event_id),
        "idempotency_key": event.idempotency_key,
        "actor": "fdai.core.control_loop",
        "producer_principal": "Forseti",
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
    system_degraded: bool = False,
    kill_switch_engaged: bool = False,
    inventory_age_seconds: int | None = None,
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
        system_degraded=system_degraded,
        kill_switch_engaged=kill_switch_engaged,
        inventory_age_seconds=inventory_age_seconds,
    )
    return _unified_audit_dict(event=event, action=action, unified=unified)


def _extract_resource_props(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Pull the resource ``props`` map out of the event payload.

    Two shapes are accepted (both documented in
    ``docs/roadmap/architecture/csp-neutrality.md § 5``):

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
    "ExecutionAuthorityDecision",
    "UnifiedRiskDecision",
    "_compute_authority",
    "_extract_environment",
    "_extract_resource_id",
    "_extract_resource_props",
    "_is_execution_success",
    "_synthetic_action_build_failure",
    "_unified_audit_dict",
    "build_shadow_authority_audit",
    "build_unified_risk_audit",
    "combine",
    "evaluate_unified",
]
