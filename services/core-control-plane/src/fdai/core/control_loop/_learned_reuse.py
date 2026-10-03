"""Default-profile boundary for T1 reuse of learned patterns (#1541).

A verified T1 match against a learned pattern is evidence that a prior resolution looks
applicable. In the default observation-first profile that evidence is recorded and the loop
stops: no Action is built from the learned action, so nothing reaches execution authorization,
the unified risk gate, a human-approval request, dynamic simulation, or dispatch. Only the
explicitly selected governed execution add-on lets the existing T1 routing propose the learned
action through those unchanged gates.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.tiers.t1_lightweight.tier import T1Decision
from fdai.core.trust_router import RoutingDecision
from fdai.core.verticals.change_safety.detector import ChangeSafetyDecision
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.stage_publisher import StageName, StagePhase
from fdai.shared.providers.state_store import StateStore

#: Terminal reason; Forseti's ActionType-free advisory Verdicts record the same value.
GOVERNED_EXECUTION_UNSELECTED_REASON = "governed_execution_unselected"


async def record_learned_reuse_advisory(
    audit_store: StateStore,
    emit_stage: Callable[..., Awaitable[None]],
    *,
    event: Event,
    decision: RoutingDecision,
    t1: T1Decision,
    cs_decision: ChangeSafetyDecision | None,
    event_id: str,
    correlation_id: str,
) -> ControlLoopResult:
    """Audit a reusable T1 match as advisory evidence and return a terminal abstain result.

    The preceding ``control_loop.t1_evaluate`` entry already retains the match; this entry
    closes the event with the reason no action was proposed.
    """
    learned = t1.best_match.action if t1.best_match is not None else None
    citing = (learned.rule_id,) if learned is not None else ()
    entry: dict[str, Any] = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "idempotency_key": event.idempotency_key,
        "actor": "fdai.core.control_loop",
        "producer_principal": "Forseti",
        "action_kind": "control_loop.t1_reuse_advisory",
        "mode": Mode.SHADOW.value,
        "decision": "abstain",
        "reason": GOVERNED_EXECUTION_UNSELECTED_REASON,
        "citing_rule_ids": list(citing),
        "learned_signature": learned.signature if learned is not None else None,
        "reused_from": learned.incident_id if learned is not None else None,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    await audit_store.append_audit_entry(entry)
    await emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.AUDIT,
        phase=StagePhase.DONE,
        detail={
            "outcome": ControlLoopOutcome.T1_REUSE_LOGGED.value,
            "reason": GOVERNED_EXECUTION_UNSELECTED_REASON,
            "mode": Mode.SHADOW.value,
        },
    )
    return ControlLoopResult(
        outcome=ControlLoopOutcome.T1_REUSE_LOGGED,
        tier="t1",
        decision="abstain",
        resource_type=decision.resource_type,
        citing_rule_ids=citing,
        reason=GOVERNED_EXECUTION_UNSELECTED_REASON,
        event_id=event_id,
        change_safety_decision=cs_decision,
        t1_decision=t1,
    )


__all__ = ["GOVERNED_EXECUTION_UNSELECTED_REASON", "record_learned_reuse_advisory"]
