"""Append-only audit writers used by the control-loop orchestrator."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from fdai.core.quality_gate import quality_decision_audit_fields
from fdai.core.tiers.t1_lightweight.tier import SimilarityMatch, T1Decision
from fdai.core.tiers.t2_reasoning import T2Decision
from fdai.core.trust_router import RoutingDecision
from fdai.rule_catalog.schema.assignment import AssignmentResolution
from fdai.rule_catalog.schema.override import Override
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.state_store import StateStore

_T1_COMPARISON_CANDIDATE_LIMIT = 5
_T1_COMPARISON_REASON_LIMIT = 32
_T1_COMPARISON_REASON_CODES = frozenset(
    {
        "no_neighbour_found",
        "invalid_pattern_library_matches",
        "invalid_similarity_score",
        "non_finite_similarity_score",
        "similarity_score_out_of_range",
        "invalid_success_rate",
        "non_finite_success_rate",
        "success_rate_out_of_range",
        "invalid_learned_action_signature",
        "invalid_learned_action_rule_id",
        "invalid_learned_action_action_type",
        "invalid_learned_action_incident_id",
        "invalid_learned_action_params",
        "invalid_learned_action_reuse_count",
        "negative_reuse_count",
        "operational_case_context_missing",
        "operational_case_action_type_changed",
        "current_case_revision_unavailable",
        "current_case_revision_changed",
        "current_reuse_verifier_unavailable",
        "current_evaluation_time_invalid",
        "current_evidence_future",
        "current_evidence_stale",
        "current_evidence_expired",
        "current_case_ref_conflict",
        "current_resource_type_changed",
        "current_failure_fingerprint_changed",
        "current_topology_role_changed",
        "current_graph_changed",
        "current_owner_changed",
        "current_precondition_failed",
        "current_target_identity_unverified",
        "current_blast_radius_exceeded",
        "current_policy_denied",
        "current_dry_run_failed",
        "current_idempotency_conflict",
        "historical_rollback_unresolved",
        "decision_evidence_admission_missing",
        "decision_evidence_evidence_mismatch",
        "decision_evidence_not_current",
        "decision_evidence_purpose_mismatch",
        "decision_evidence_scope_mismatch",
        "decision_evidence_source_revision_mismatch",
        "t1_deadline_exceeded",
        "baseline_comparison_stopped",
        "no_retained_pattern",
        "retained_pattern_source_unavailable",
        "retained_pattern_projection_unavailable",
        "retained_pattern_action_unavailable",
        "retained_pattern_source_changed",
        "retained_pattern_evidence_changed",
        "retained_pattern_qualification_unavailable",
        "retained_pattern_qualification_rejected",
        "retained_pattern_positive_case_required",
        "retained_pattern_statistics_unavailable",
        "retained_pattern_context_mismatch",
        "retained_pattern_action_unregistered",
        "retained_pattern_argument_schema_unavailable",
        "retained_pattern_arguments_invalid",
        "retained_pattern_similarity_invalid",
        "retained_pattern_insufficient_positive_cases",
        "retained_pattern_reuse_statistics_unavailable",
    }
)


def _t1_comparison_reason(reason: str) -> dict[str, str]:
    """Keep known diagnostics readable, but never retain arbitrary provider text."""
    if reason in _T1_COMPARISON_REASON_CODES:
        code = reason
    elif reason.startswith("similarity="):
        code = "similarity_below_threshold"
    elif reason.startswith("success_rate="):
        code = "success_rate_below_floor"
    elif reason.partition(":")[0] in (
        "t1_provider_error",
        "current_reuse_verification_error",
        "t1_candidate_error",
        "retained_pattern_error",
    ):
        code = reason.partition(":")[0]
    else:
        code = "redacted"
    return {"code": code, "digest": "sha256:" + hashlib.sha256(reason.encode("utf-8")).hexdigest()}


def _t1_comparison_outcome(
    *,
    outcome: str,
    match: SimilarityMatch | None,
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    """Identify a pattern without copying parameters, targets, or raw provenance."""
    identity_digest = None
    if match is not None:
        action = match.action
        identity = (
            action.signature,
            action.rule_id,
            action.action_type,
            action.incident_id,
            action.operational_case.case_ref if action.operational_case is not None else None,
        )
        identity_digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        )
    return {
        "outcome": outcome,
        "match_identity_digest": identity_digest,
        "reasons": [
            _t1_comparison_reason(reason) for reason in reasons[:_T1_COMPARISON_REASON_LIMIT]
        ],
        "reason_count": len(reasons),
        "reasons_truncated": len(reasons) > _T1_COMPARISON_REASON_LIMIT,
    }


def _t1_comparison_audit_fields(t1: T1Decision) -> dict[str, Any]:
    comparison = t1.eligibility_comparison
    if comparison is None:
        return {}
    checks = comparison.candidates[:_T1_COMPARISON_CANDIDATE_LIMIT]
    selected = comparison.challenger_match
    stop_reason = comparison.stop_reason
    challenger_reasons: tuple[str, ...] = ()
    if selected is None:
        challenger_reasons = (
            (stop_reason,)
            if stop_reason is not None
            else (comparison.candidates[-1].reasons if comparison.candidates else ())
        )
    return {
        "t1_eligibility_comparison": {
            "schema_version": "1.0.0",
            "mode": Mode.SHADOW.value,
            "execution_authority": False,
            "promotion_authority": False,
            "actual_selection_changed": False,
            "baseline": _t1_comparison_outcome(
                outcome=t1.outcome.value, match=t1.best_match, reasons=t1.reasons
            ),
            "challenger": _t1_comparison_outcome(
                outcome="eligible"
                if selected is not None
                else ("stopped" if stop_reason else "exhausted"),
                match=selected,
                reasons=challenger_reasons,
            ),
            "checked_count": len(comparison.candidates),
            "recorded_candidate_count": len(checks),
            "candidates_truncated": len(comparison.candidates) > len(checks),
            "candidates": [
                _t1_comparison_outcome(
                    outcome="eligible" if check.eligible else "ineligible",
                    match=check.match,
                    reasons=check.reasons,
                )
                for check in checks
            ],
            "stop_reason": _t1_comparison_reason(stop_reason) if stop_reason is not None else None,
        }
    }


def _t1_retained_comparison_audit_fields(t1: T1Decision) -> dict[str, Any]:
    comparison = t1.retained_pattern_comparison
    if comparison is None:
        return {}
    checks = comparison.candidates[:_T1_COMPARISON_CANDIDATE_LIMIT]
    qualified = comparison.final_qualification is not None or comparison.final_lease is not None
    return {
        "t1_retained_pattern_comparison": {
            "schema_version": "1.0.0",
            "mode": Mode.SHADOW.value,
            "execution_authority": False,
            "promotion_authority": False,
            "operationally_proven": False,
            "local_lease_dependencies_digest": (
                comparison.final_lease.dependencies_digest
                if comparison.final_lease is not None
                else None
            ),
            "local_lease_tuple_digest": (
                comparison.final_lease.tuple_digest if comparison.final_lease is not None else None
            ),
            "local_lease_read_admission_digest": (
                comparison.final_lease.read_admission.receipt_digest
                if comparison.final_lease is not None
                else None
            ),
            "local_lease_reuse_admission_digest": (
                comparison.final_lease.reuse_admission.receipt_digest
                if comparison.final_lease is not None
                else None
            ),
            "qualification_receipt_digest": (
                comparison.final_qualification.receipt_digest
                if comparison.final_qualification is not None
                else None
            ),
            "qualification_tuple_digest": (
                comparison.final_qualification.evidence_digest
                if comparison.final_qualification is not None
                else None
            ),
            "actual_selection_changed": False,
            "pattern_ids": [
                value
                if re.fullmatch(r"[a-f0-9]{64}", value)
                else hashlib.sha256(value.encode()).hexdigest()
                for value in comparison.pattern_ids[:_T1_COMPARISON_CANDIDATE_LIMIT]
            ],
            "statistics_refs": [
                value
                if re.fullmatch(r"[a-f0-9]{64}", value)
                else hashlib.sha256(value.encode()).hexdigest()
                for value in comparison.statistics_refs[:_T1_COMPARISON_CANDIDATE_LIMIT]
            ],
            "checked_count": len(comparison.candidates),
            "recorded_candidate_count": len(checks),
            "candidates_truncated": len(comparison.candidates) > len(checks),
            "candidates": [
                _t1_comparison_outcome(
                    outcome="eligible" if check.eligible and qualified else "ineligible",
                    match=check.match,
                    reasons=check.reasons,
                )
                for check in checks
            ],
            "challenger": _t1_comparison_outcome(
                outcome="eligible"
                if comparison.challenger_match is not None and qualified
                else "held",
                match=comparison.challenger_match if qualified else None,
                reasons=(),
            ),
            "stop_reason": (
                _t1_comparison_reason(comparison.stop_reason)
                if comparison.stop_reason is not None
                else None
            ),
        }
    }


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


async def write_override_resolution_audit(
    audit_store: StateStore,
    *,
    event: Event,
    resource_id: str,
    rule_id: str,
    override: Override,
) -> None:
    """Append-only evidence for one override applying to a T0 finding.

    rule-governance.md "Overrides § Rules (MUST)" ("Audit-first": every
    override create/modify/remove event is audited) and "§ Feedback Loop"
    (overrides are inputs to the discovery loop). ``rule_id``, ``scope``, and
    ``mode`` are exactly the facts
    ``operational_learning/discovery_contracts.py``'s
    ``DiscoverySignalKind.OPERATIONAL`` input needs to eventually recognize a
    recurring or long-lived override and propose a rule revision/retirement -
    this entry is that feedback signal's evidence source, not a new bus topic
    (agent-pantheon.instructions.md: ``object.override`` is not registered).
    """
    await audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Mimir",
            "action_kind": "governance.override_resolved",
            "mode": Mode.SHADOW.value,
            "rule_id": rule_id,
            "resource_id": resource_id,
            "override_id": override.id,
            "override_mode": override.mode.value,
            "override_scope": override.scope.render(),
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
    action_kind: str = "control_loop.abstain",
) -> None:
    await audit_store.append_audit_entry(
        {
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id or str(event.event_id),
            "idempotency_key": event.idempotency_key,
            "actor": "fdai.core.control_loop",
            "producer_principal": "Heimdall" if stage == "trust_router" else "Forseti",
            "action_kind": action_kind,
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
    verification = t1.current_reuse_verification
    best_summary: dict[str, Any] | None = None
    if best is not None:
        best_summary = {
            "score": best.score,
            "rule_id": best.action.rule_id,
            "action_type": best.action.action_type,
            "success_rate": best.action.success_rate,
            "reused_from": best.action.incident_id,
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
            "tier": "t1",
            "stage": "t1_similarity",
            "t1_outcome": t1.outcome.value,
            "t1_threshold": t1.threshold,
            "t1_reason": t1.reason,
            "t1_reasons": list(t1.reasons),
            "t1_best_match": best_summary,
            "t1_current_reuse_verification": (
                {
                    "case_ref": verification.case_ref,
                    "observed_at": verification.observed_at.isoformat(),
                    "evidence_refs": list(verification.evidence_refs),
                    "failure_fingerprint": verification.failure_fingerprint,
                    "resource_type": verification.resource_type,
                    "topology_role": verification.topology_role,
                    "graph_digest": verification.graph_digest,
                    "owner_digest": verification.owner_digest,
                    "preconditions_passed": verification.preconditions_passed,
                    "target_identity_verified": verification.target_identity_verified,
                    "blast_radius_within_limit": verification.blast_radius_within_limit,
                    "policy_allowed": verification.policy_allowed,
                    "dry_run_passed": verification.dry_run_passed,
                    "idempotency_available": verification.idempotency_available,
                    "rollback_resolved": verification.rollback_resolved,
                }
                if verification is not None
                else None
            ),
            "resource_type": decision.resource_type,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
            **_t1_comparison_audit_fields(t1),
            **_t1_retained_comparison_audit_fields(t1),
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
            "tier": "t2",
            "stage": "t2_reasoning",
            "t2_outcome": t2.outcome.value,
            "t2_reason": t2.reason,
            "t2_candidate": candidate_summary,
            "t2_quality": quality_summary,
            "resource_type": decision.resource_type,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }
    )
