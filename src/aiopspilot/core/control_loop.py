"""Control-loop orchestrator — wires the P1 pipeline end-to-end.

Composes the five P1 subsystems currently implemented:

.. code-block:: text

    event_ingest ──► trust_router ──► T0Engine ──► ActionBuilder ──► ShadowExecutor
                                       │
                                       └──► abstain-audit (fallback)

No T1 / T2 / risk-gate is invoked; those land in later phases behind
their own DI seams. The orchestrator lives in ``core/`` because it is
the safety-critical assembly point — every failure MUST audit, and
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
from aiopspilot.core.tiers.t0_deterministic import T0Engine
from aiopspilot.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from aiopspilot.core.verticals.change_safety_detector import (
    ChangeSafetyDecision,
    ChangeSafetyDetector,
)
from aiopspilot.shared.contracts.models import Event, Mode, Rule
from aiopspilot.shared.providers.state_store import StateStore


class ControlLoopOutcome(StrEnum):
    """Top-level outcome for one :meth:`ControlLoop.process` call."""

    DEDUPED = "deduped"
    """Duplicate delivery — no audit written (previous delivery owns it)."""

    ABSTAINED_ROUTING = "abstained_routing"
    """Trust-router found no candidate rule; no T0 evaluation."""

    ABSTAINED_T0 = "abstained_t0"
    """T0 evaluated candidates and produced no findings."""

    EXECUTED = "executed"
    """One or more actions were built + executed (shadow PRs opened)."""

    ABSTAINED_ACTION_BUILD = "abstained_action_build"
    """A finding's ActionType could not be resolved; the loop fails
    closed instead of publishing an invalid Action."""


@dataclass(frozen=True, slots=True)
class ControlLoopResult:
    """Aggregate result for one event.

    ``decision`` follows the audit vocabulary defined in
    ``docs/roadmap/llm-strategy.md``:

    - ``auto`` — T0 matched and an action was executed (shadow PR opened).
    - ``abstain`` — routing or T0 abstained.
    - ``dedupe`` — duplicate delivery.

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
    ) -> None:
        self._event_ingest = event_ingest
        self._trust_router = trust_router
        self._t0_engine = t0_engine
        self._action_builder = action_builder
        self._executor = executor
        self._audit_store = audit_store
        self._rules_by_id = dict(rules_by_id)
        self._change_safety_detector = change_safety_detector

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
        # routing — it is a shadow-mode observability + reconcile-PR
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

        if decision.resource_type is None:  # pragma: no cover — belt-and-suspenders
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

        # 4. Build + execute one action per finding
        exec_results: list[ExecutionResult] = []
        for finding in verdict.findings:
            rule = self._rules_by_id.get(finding.rule_id)
            if rule is None:  # pragma: no cover — index/catalog inconsistency
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
                exec_results.append(  # noqa: E501 — surfaces the failure to the caller
                    _synthetic_action_build_failure(event=event, finding=finding, reason=str(exc))
                )
                continue

            result = await self._executor.execute(action=action, rule=rule)
            exec_results.append(result)

        # If EVERY finding hit a build error, treat the overall outcome
        # as ABSTAINED_ACTION_BUILD so a monitor can page on it.
        overall = (
            ControlLoopOutcome.EXECUTED
            if any(_is_execution_success(r) for r in exec_results)
            else ControlLoopOutcome.ABSTAINED_ACTION_BUILD
        )
        return ControlLoopResult(
            outcome=overall,
            tier="t0",
            decision=("auto" if overall is ControlLoopOutcome.EXECUTED else "abstain"),
            resource_type=decision.resource_type,
            citing_rule_ids=tuple(f.rule_id for f in verdict.findings),
            execution_results=tuple(exec_results),
            event_id=str(event.event_id),
            change_safety_decision=cs_decision,
        )

    # ------------------------------------------------------------------
    # audit helper
    # ------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_resource_props(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Pull the resource ``props`` map out of the event payload.

    Two shapes are accepted (both documented in
    ``docs/roadmap/csp-neutrality.md § 5``):

    1. ``payload['resource']['props']`` — matches
       :class:`ResourceRecord` produced by the Inventory adapter.
    2. ``payload['props']`` — a legacy flat form used by some Phase 0
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
