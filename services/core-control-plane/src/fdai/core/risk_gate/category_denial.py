"""Category-only denials: the one denial the full-authority development profile may park.

Constitution Article 8 keeps every risk class recorded for replay but forbids denying a registered
ActionType solely by its category inside the bound test scope. A denial counts as category-only
only when every matching deny rule conditions nothing but ActionType category dimensions, the
table without those rules would not deny, and every other ceiling axis already admits human
approval. A policy violation, stale or missing evidence, a role gap, the kill switch, degradation,
a tier cap, an automation hold, an evidence conflict, or an upstream verifier keeps the denial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fdai.core.risk_gate.ceiling import AxisLevel, ResolvedCeiling
from fdai.core.risk_gate.gate import RiskDecisionOutcome
from fdai.core.risk_gate.live_probe import LiveProbeObservation
from fdai.core.risk_gate.risk_table import FeatureVector, RiskLevel, RiskTable
from fdai.shared.contracts.models import ActionInterface, Mode, OntologyActionType

if TYPE_CHECKING:
    from fdai.core.risk_gate.evaluator import UnifiedRiskDecision

# Risk-table dimensions derived only from the ActionType itself (risk-classification.md,
# Classification Dimensions). Every other dimension describes context, evidence, or policy.
CATEGORY_DIMENSIONS: frozenset[str] = frozenset(
    {
        "blast_radius",
        "data_plane_touched",
        "destructive",
        "irreversible",
        "reversible",
        "rollback_path",
    }
)
# The only ceiling axes that deny because of the ActionType category.
CATEGORY_AXES: frozenset[str] = frozenset({"risk_table", "static_blast"})
# Runtime-gate reasons that report missing or stale inventory evidence, not a category.
_GRAPH_EVIDENCE_REASON = "graph_fresh_precondition"


@dataclass(frozen=True, slots=True)
class CategoryDenial:
    """The category facts behind one category-only denial and the table's residual decision.

    ``residual_*`` is the table verdict with the category deny rules removed, so the audit shows
    the requirement the development Owner's approval stands in for.
    """

    rule_ids: tuple[str, ...]
    axes: tuple[str, ...]
    residual_rule_id: str
    residual_decision: str
    residual_quorum: int

    def as_audit_dict(self) -> dict[str, Any]:
        """Return the JSON-safe audit projection recorded in the park block."""
        return {
            "rule_ids": list(self.rule_ids),
            "axes": list(self.axes),
            "residual_rule_id": self.residual_rule_id,
            "residual_decision": self.residual_decision,
            "residual_quorum": self.residual_quorum,
        }


def category_only_denial(
    *,
    table: RiskTable,
    feature: FeatureVector,
    ceiling: ResolvedCeiling,
) -> CategoryDenial | None:
    """Return the category facts only when the ActionType category is the sole denial source.

    First-match evaluation can hide a second deny rule behind a category rule, so every matching
    deny rule must condition only category dimensions, and the table without them must not deny.
    """
    lookup = feature.as_lookup()
    category_rules = tuple(
        rule
        for rule in table.rules
        if rule.decision is RiskLevel.DENY
        and rule.conditions
        and rule.dimensions <= CATEGORY_DIMENSIONS
        and rule.matches(lookup)
    )
    residual = RiskTable(
        version=table.version,
        owner_group=table.owner_group,
        rules=tuple(rule for rule in table.rules if rule not in category_rules),
    ).evaluate(feature)
    if residual.decision is RiskLevel.DENY:
        return None
    denying = tuple(axis.name for axis in ceiling.axes if axis.level is AxisLevel.DENY)
    # Every other axis must already admit human approval, so only a category axis may deny.
    if not denying or any(
        axis.name not in CATEGORY_AXES and axis.level < AxisLevel.ENFORCE_HIL
        for axis in ceiling.axes
    ):
        return None
    return CategoryDenial(
        rule_ids=tuple(rule.rule_id for rule in category_rules),
        axes=denying,
        residual_rule_id=residual.rule_id,
        residual_decision=residual.decision.value,
        residual_quorum=residual.quorum,
    )


def development_evidence_unsafe(
    action_type: OntologyActionType,
    *,
    policy_violation: bool,
    graph_stale: bool | None,
    graph_affected: int | None,
    system_degraded: bool,
    kill_switch_engaged: bool,
    live_probe_observation: LiveProbeObservation | None,
    live_probe_failure_streak: int,
) -> bool:
    """Return whether a safety or evidence prerequisite of the development path failed."""
    return (
        policy_violation
        or _graph_evidence_missing(
            action_type,
            graph_stale=graph_stale,
            graph_affected=graph_affected,
        )
        or system_degraded
        or kill_switch_engaged
        or _live_probe_evidence_stale(
            action_type,
            live_probe_observation,
            live_probe_failure_streak,
        )
    )


def development_category_denial(
    unified: UnifiedRiskDecision,
    *,
    table: RiskTable,
    action_type: OntologyActionType,
) -> CategoryDenial | None:
    """Return the category facts when a unified denial may park for the development Owner.

    Only the authority side may deny: the runtime gate must already admit human approval without
    a stale-inventory reason, current evidence must carry no conflict, and every development
    safety and evidence prerequisite recorded on the authority decision must hold.
    """
    authority = unified.authority
    gate = unified.gate
    if (
        not unified.is_denied
        or authority is None
        or authority.development_authority is not None
        or authority.catalog_version != table.version
        or gate.outcome is RiskDecisionOutcome.DENY
        or (gate.outcome is RiskDecisionOutcome.AUTO and gate.effective_mode is not Mode.ENFORCE)
        or any(reason.startswith(_GRAPH_EVIDENCE_REASON) for reason in gate.reasons)
        or not unified.evidence_conflict_clear
    ):
        return None
    inputs = authority.ceiling_inputs
    feature = authority.feature_vector
    if development_evidence_unsafe(
        action_type,
        policy_violation=feature.policy_violation is True,
        graph_stale=feature.graph_stale,
        graph_affected=inputs.graph_affected,
        system_degraded=inputs.system_degraded,
        kill_switch_engaged=inputs.kill_switch_engaged,
        live_probe_observation=inputs.live_probe,
        live_probe_failure_streak=inputs.live_probe_failure_streak,
    ):
        return None
    return category_only_denial(table=table, feature=feature, ceiling=authority.resolved_ceiling)


def _live_probe_evidence_stale(
    action_type: OntologyActionType,
    observation: LiveProbeObservation | None,
    failure_streak: int,
) -> bool:
    """Keep unavailable, stale, substituted, or degraded required evidence closed."""
    ref = action_type.live_probe_ref
    if ref is None:
        return False
    return (
        failure_streak > 0
        or observation is None
        or observation.probe_id != ref
        or observation.degraded
        or not observation.is_fresh
    )


def _graph_evidence_missing(
    action_type: OntologyActionType,
    *,
    graph_stale: bool | None,
    graph_affected: int | None,
) -> bool:
    requires_fresh = ActionInterface.REQUIRES_INVENTORY_FRESH in action_type.interfaces
    graph_derived = (
        action_type.blast_radius is not None
        and action_type.blast_radius.computation.value == "graph_derived"
    )
    return requires_fresh and graph_stale is not False or graph_derived and graph_affected is None


__all__ = [
    "CATEGORY_AXES",
    "CATEGORY_DIMENSIONS",
    "CategoryDenial",
    "category_only_denial",
    "development_category_denial",
    "development_evidence_unsafe",
]
