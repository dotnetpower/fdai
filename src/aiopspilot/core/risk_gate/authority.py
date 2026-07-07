"""Unified execution-authority evaluation - the one pipeline.

Ties the three previously-disconnected pieces together:

    ActionType + context
      -> feature_vector_from(...)          (feature.py)
      -> RiskTable.evaluate(...)           (risk_table.py, Axis A)
      -> resolve_ceiling(..., risk_table=verdict)   (ceiling.py, 6 axes)
      -> ExecutionAuthorityDecision

The risk-classification table verdict is the authoritative baseline; the
six-axis ceiling combines with it via ``min()`` and can only ever lower
autonomy (execution-model.md 2). This function is pure and deterministic:
the probe result and every context signal are inputs, so a replay
reproduces the decision exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiopspilot.core.risk_gate.ceiling import (
    AxisLevel,
    Env,
    PrincipalRole,
    ProbeResult,
    ResolvedCeiling,
    resolve_ceiling,
)
from aiopspilot.core.risk_gate.feature import feature_vector_from
from aiopspilot.core.risk_gate.risk_table import (
    FeatureVector,
    RiskTable,
    RiskTableVerdict,
)
from aiopspilot.shared.contracts.models import OntologyActionType, Tier

# AxisLevel -> the terminal decision word used on the audit entry and by
# the control loop. SHADOW_ONLY surfaces as "shadow" (judge and log).
_LEVEL_TO_DECISION: dict[AxisLevel, str] = {
    AxisLevel.ENFORCE_AUTO: "auto",
    AxisLevel.ENFORCE_HIL: "hil",
    AxisLevel.SHADOW_ONLY: "shadow",
    AxisLevel.DENY: "deny",
}


@dataclass(frozen=True, slots=True)
class ExecutionAuthorityDecision:
    """The single result of the unified pipeline."""

    final_level: AxisLevel
    quorum: int
    resolved_ceiling: ResolvedCeiling
    table_verdict: RiskTableVerdict
    feature_vector: FeatureVector

    @property
    def decision(self) -> str:
        return _LEVEL_TO_DECISION[self.final_level]

    @property
    def is_auto(self) -> bool:
        return self.final_level is AxisLevel.ENFORCE_AUTO

    @property
    def requires_hil(self) -> bool:
        return self.final_level is AxisLevel.ENFORCE_HIL

    @property
    def is_denied(self) -> bool:
        return self.final_level is AxisLevel.DENY

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "quorum": self.quorum,
            "matched_rule_id": self.table_verdict.rule_id,
            "resolved_ceiling": self.resolved_ceiling.as_audit_dict(),
        }


def _ceiling_env(environment: str) -> Env:
    """Normalize the risk-table environment word to the ceiling's Env."""
    return "prod" if environment == "prod" else "non_prod"


def evaluate_execution_authority(
    *,
    tier: Tier,
    action_type: OntologyActionType,
    table: RiskTable,
    principal_role: PrincipalRole,
    environment: str,
    policy_violation: bool = False,
    verifier_confidence: float | None = None,
    cost_impact_monthly: float | None = None,
    graph_stale: bool | None = None,
    cross_resource_impact: int | None = None,
    allowlist_prod_auto: bool = False,
    graph_affected: int | None = None,
    live_probe: ProbeResult | None = None,
) -> ExecutionAuthorityDecision:
    """Run the full pipeline and return one combined decision.

    ``environment`` is the normalized risk-table word (``"prod"`` /
    ``"non-prod"``); it is mapped to the ceiling's ``prod`` / ``non_prod``
    internally so both axes see a single environment classification.
    """
    feature = feature_vector_from(
        action_type,
        environment=environment,
        policy_violation=policy_violation,
        verifier_confidence=verifier_confidence,
        cost_impact_monthly=cost_impact_monthly,
        graph_stale=graph_stale,
        cross_resource_impact=cross_resource_impact,
        allowlist_prod_auto=allowlist_prod_auto,
    )
    verdict = table.evaluate(feature)
    ceiling = resolve_ceiling(
        tier=tier,
        action_type=action_type,
        risk_table=verdict,
        principal_role=principal_role,
        env=_ceiling_env(environment),
        graph_affected=graph_affected,
        live_probe=live_probe,
    )
    return ExecutionAuthorityDecision(
        final_level=ceiling.final_level,
        quorum=ceiling.final_quorum,
        resolved_ceiling=ceiling,
        table_verdict=verdict,
        feature_vector=feature,
    )


__all__ = ["ExecutionAuthorityDecision", "evaluate_execution_authority"]
