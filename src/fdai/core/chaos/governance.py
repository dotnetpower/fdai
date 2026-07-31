"""Fail-closed eligibility for a human-approved chaos enforce run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChaosEligibilityContext:
    catalog_valid: bool
    scenario_promoted: bool
    action_types_promoted: bool
    causal_hypothesis_ref: str
    refutation_query_ref: str
    explicit_targets: tuple[str, ...]
    supported_environment: bool
    owner_ref: str
    maintenance_window_active: bool
    graph_complete: bool
    objective_headroom: bool
    recovery_ready: bool
    telemetry_ready: bool
    no_conflicting_work: bool
    dry_run_receipt: str
    locks_acquired: bool
    idempotency_key: str
    kill_switch_clear: bool
    stop_conditions_ready: bool
    audit_ready: bool
    approval_principal: str
    approver_ids: tuple[str, ...]
    initiator_id: str
    production_or_stateful: bool = False


@dataclass(frozen=True, slots=True)
class ChaosEligibilityDecision:
    eligible: bool
    reasons: tuple[str, ...]
    quorum_required: int


def evaluate_chaos_eligibility(context: ChaosEligibilityContext) -> ChaosEligibilityDecision:
    reasons: list[str] = []
    boolean_gates = {
        "catalog_invalid": context.catalog_valid,
        "scenario_not_promoted": context.scenario_promoted,
        "action_type_not_promoted": context.action_types_promoted,
        "environment_unsupported": context.supported_environment,
        "maintenance_window_inactive": context.maintenance_window_active,
        "graph_incomplete": context.graph_complete,
        "objective_headroom_insufficient": context.objective_headroom,
        "recovery_not_ready": context.recovery_ready,
        "telemetry_not_ready": context.telemetry_ready,
        "conflicting_work_open": context.no_conflicting_work,
        "locks_not_acquired": context.locks_acquired,
        "kill_switch_active": context.kill_switch_clear,
        "stop_conditions_unavailable": context.stop_conditions_ready,
        "audit_unavailable": context.audit_ready,
    }
    reasons.extend(reason for reason, passed in boolean_gates.items() if not passed)
    required_strings = {
        "causal_hypothesis_missing": context.causal_hypothesis_ref,
        "refutation_query_missing": context.refutation_query_ref,
        "owner_missing": context.owner_ref,
        "dry_run_missing": context.dry_run_receipt,
        "idempotency_key_missing": context.idempotency_key,
    }
    reasons.extend(reason for reason, value in required_strings.items() if not value.strip())
    targets_missing = not context.explicit_targets or any(
        not target.strip() for target in context.explicit_targets
    )
    if targets_missing:
        reasons.append("explicit_targets_missing")
    quorum_required = 2 if context.production_or_stateful else 1
    normalized_approvers = {item.casefold() for item in context.approver_ids if item.strip()}
    if context.approval_principal != "Var":
        reasons.append("var_approval_required")
    if context.initiator_id.casefold() in normalized_approvers:
        reasons.append("self_approval_forbidden")
    if len(normalized_approvers) < quorum_required:
        reasons.append("approval_quorum_not_met")
    return ChaosEligibilityDecision(
        eligible=not reasons,
        reasons=tuple(sorted(set(reasons))),
        quorum_required=quorum_required,
    )


__all__ = [
    "ChaosEligibilityContext",
    "ChaosEligibilityDecision",
    "evaluate_chaos_eligibility",
]
