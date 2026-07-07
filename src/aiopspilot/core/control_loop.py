"""Control-loop orchestrator - wires the P1 pipeline end-to-end.

Composes the five P1 subsystems currently implemented:

.. code-block:: text

    event_ingest ──► trust_router ──► T0Engine ──► ActionBuilder ──► ShadowExecutor
                                       │
                                       └──► abstain-audit (fallback)

No T1 / T2 tier is invoked; those land in later phases behind their own
DI seams. The unified risk-gate pipeline
(:func:`aiopspilot.core.risk_gate.authority.evaluate_execution_authority`)
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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aiopspilot.core.event_ingest import EventIngest
from aiopspilot.core.executor import ExecutionResult, ExecutorOutcome, ShadowExecutor
from aiopspilot.core.executor.action_builder import ActionBuilder, ActionBuildError
from aiopspilot.core.risk_gate.authority import (
    ExecutionAuthorityDecision,
    evaluate_execution_authority,
)
from aiopspilot.core.risk_gate.evaluator import UnifiedRiskDecision, combine
from aiopspilot.core.risk_gate.gate import RiskGate
from aiopspilot.core.risk_gate.risk_table import RiskTable
from aiopspilot.core.tiers.t0_deterministic import T0Engine
from aiopspilot.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from aiopspilot.core.verticals.change_safety_detector import (
    ChangeSafetyDecision,
    ChangeSafetyDetector,
)
from aiopspilot.shared.contracts.models import (
    Action,
    CeilingRole,
    Event,
    Mode,
    OntologyActionType,
    Rule,
    Tier,
)
from aiopspilot.shared.providers.cost_estimator import (
    CostEstimator,
    resolve_cost_impact_monthly,
)
from aiopspilot.shared.providers.state_store import StateStore


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
    execution_results: tuple[ExecutionResult, ...] = ()
    reason: str | None = None
    event_id: str | None = None
    change_safety_decision: ChangeSafetyDecision | None = None
    """When the event was routed through the out-of-band detector, the
    detector's classification is surfaced here so a monitor / test can
    assert on it without inspecting the audit log."""


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

    async def process(self, raw_event: Event | Mapping[str, Any]) -> ControlLoopResult:
        # 1. Ingest + dedupe
        event = self._event_ingest.ingest(raw_event)
        if event is None:
            return ControlLoopResult(
                outcome=ControlLoopOutcome.DEDUPED,
                tier="abstain",
                decision="dedupe",
                resource_type=None,
                reason="duplicate_idempotency_key",
            )

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
            await self._write_abstain_audit(
                event=event,
                decision=decision,
                reason=decision.reason or "trust_router_abstain",
                stage="trust_router",
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
        exec_results: list[ExecutionResult] = []
        routed: list[str] = []
        for finding in verdict.findings:
            rule = self._rules_by_id.get(finding.rule_id)
            if rule is None:  # pragma: no cover - index/catalog inconsistency
                raise KeyError(
                    f"rule {finding.rule_id!r} appears in T0 findings but is "
                    "not in the rules_by_id map"
                )
            try:
                action = self._action_builder.build_from_finding(
                    event=event, finding=finding, rule=rule
                )
            except ActionBuildError as exc:
                # Fail-closed for this finding; other findings keep going.
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
            if unified is not None and (unified.is_denied or unified.requires_hil):
                # Routed to HIL / denied by the unified risk gate: do NOT
                # publish a PR. The audit entry (written above) records why.
                routed.append("deny" if unified.is_denied else "hil")
                continue
            result = await self._executor.execute(action=action, rule=rule)
            exec_results.append(result)

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
        :class:`~aiopspilot.shared.providers.cost_estimator.CostEstimator`
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
                "actor": "aiopspilot.core.control_loop",
                "action_kind": "control_loop.abstain",
                "mode": Mode.SHADOW.value,
                "stage": stage,
                "reason": reason,
                "resource_type": decision.resource_type,
                "candidate_rule_ids": list(decision.candidate_rule_ids),
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
    :class:`~aiopspilot.shared.providers.cost_estimator.CostEstimator`
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
        "actor": "aiopspilot.core.control_loop",
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
        "actor": "aiopspilot.core.control_loop",
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
    single :class:`~aiopspilot.core.risk_gate.evaluator.UnifiedRiskDecision`
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


def _is_execution_success(result: ExecutionResult | Any) -> bool:
    if not hasattr(result, "outcome"):
        return False
    return result.outcome in (
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
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
