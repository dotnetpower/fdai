"""Append-only audit writers used by the control-loop orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.core.quality_gate import quality_decision_audit_fields
from fdai.core.tiers.t1_lightweight.tier import T1Decision
from fdai.core.tiers.t2_reasoning import T2Decision
from fdai.core.trust_router import RoutingDecision
from fdai.rule_catalog.schema.assignment import AssignmentResolution
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.state_store import StateStore


async def write_governance_assignment_audit(
    audit_store: StateStore,
    *,
    event: Event,
    resource_id: str,
    resolution: AssignmentResolution,
) -> None:
    await audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Mimir",
            "action_kind": "governance.assignment_resolved",
            "mode": Mode.SHADOW.value,
            "rule_id": resolution.rule_id,
            "resource_id": resource_id,
            "effective_effect": resolution.effective_effect.value,
            "enforcement": resolution.enforcement.value,
            "winning_assignment_id": resolution.winning_assignment_id,
            "overridden_assignment_ids": list(resolution.overridden_assignment_ids),
            "parameter_tie": resolution.parameter_tie,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
    )


async def write_abstain_audit(
    audit_store: StateStore,
    *,
    event: Event,
    decision: RoutingDecision,
    reason: str,
    stage: str,
) -> None:
    await audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Heimdall" if stage == "trust_router" else "Forseti",
            "action_kind": "control_loop.abstain",
            "mode": Mode.SHADOW.value,
            "stage": stage,
            "reason": reason,
            "resource_type": decision.resource_type,
            "candidate_rule_ids": list(decision.candidate_rule_ids),
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
    )


async def record_unhandled_failure(
    audit_store: StateStore,
    *,
    payload: dict[str, Any] | Any,
    reason: str,
) -> None:
    event_id = payload.get("event_id") or payload.get("id") or "unknown"
    correlation_id = payload.get("correlation_id") or event_id
    idempotency_key = payload.get("idempotency_key") or "unknown"
    await audit_store.append_audit_entry(
        {
            "event_id": str(event_id),
            "correlation_id": str(correlation_id),
            "idempotency_key": str(idempotency_key),
            "actor": "fdai.core.control_loop",
            "action_kind": "control_loop.unhandled_failure",
            "mode": Mode.SHADOW.value,
            "decision": "abstain",
            "reason": reason,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
    )


async def write_t1_audit(
    audit_store: StateStore,
    *,
    event: Event,
    decision: RoutingDecision,
    t1: T1Decision,
) -> None:
    best = t1.best_match
    best_summary: dict[str, Any] | None = None
    if best is not None:
        best_summary = {
            "score": best.score,
            "rule_id": best.action.rule_id,
            "action_type": best.action.action_type,
            "success_rate": best.action.success_rate,
        }
    await audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Forseti",
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


async def write_t2_audit(
    audit_store: StateStore,
    *,
    event: Event,
    decision: RoutingDecision,
    t2: T2Decision,
) -> None:
    candidate_summary: dict[str, Any] | None = None
    if t2.candidate is not None:
        candidate_summary = {
            "action_type": t2.candidate.action_type,
            "target_resource_ref": t2.candidate.target_resource_ref,
            "cited_rule_ids": list(t2.candidate.cited_rule_ids),
        }
    quality_summary: dict[str, Any] | None = None
    if t2.quality_decision is not None:
        quality_summary = quality_decision_audit_fields(t2.quality_decision)
    await audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Forseti",
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
