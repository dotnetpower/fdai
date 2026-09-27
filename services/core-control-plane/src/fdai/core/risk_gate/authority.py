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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.core.risk_gate.ceiling import (
    AxisLevel,
    Env,
    PrincipalRole,
    ResolvedCeiling,
    resolve_ceiling,
)
from fdai.core.risk_gate.feature import feature_vector_from
from fdai.core.risk_gate.live_probe import (
    LiveProbeObservation,
    resolve_live_probe_axis,
)
from fdai.core.risk_gate.risk_table import (
    FeatureVector,
    RiskTable,
    RiskTableVerdict,
)
from fdai.shared.contracts.development_authority import (
    DevelopmentAuthorityDecision,
    development_authority_audit,
    evaluate_development_authority,
)
from fdai.shared.contracts.models import (
    ActionInterface,
    DevelopmentActionConfirmation,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
    Tier,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
    resolve_development_binding,
)

# AxisLevel -> the terminal decision word used on the audit entry and by
# the control loop. SHADOW_ONLY surfaces as "shadow" (judge and log).
_LEVEL_TO_DECISION: dict[AxisLevel, str] = {
    AxisLevel.ENFORCE_AUTO: "auto",
    AxisLevel.ENFORCE_HIL: "hil",
    AxisLevel.SHADOW_ONLY: "shadow",
    AxisLevel.DENY: "deny",
}


@dataclass(frozen=True, slots=True)
class CeilingInputs:
    """The ceiling inputs the feature vector does not already carry.

    Recorded verbatim on the audit entry so a replay reconstructs the same
    six-axis ceiling from the record instead of re-reading a live probe or
    re-observing control-plane health (execution-model.md 4.2).
    """

    principal_role: str | None
    graph_affected: int | None
    live_probe: LiveProbeObservation | None
    live_probe_failure_streak: int
    system_degraded: bool
    kill_switch_engaged: bool

    def as_audit_dict(self) -> dict[str, Any]:
        probe = self.live_probe
        return {
            "principal_role": self.principal_role,
            "graph_affected": self.graph_affected,
            "live_probe": None
            if probe is None
            else {
                "probe_id": probe.probe_id,
                "verdict": probe.verdict.value,
                "degraded": probe.degraded,
                "age_seconds": probe.age_seconds,
                "max_age_seconds": probe.max_age_seconds,
                "reason": probe.reason,
                "metrics": dict(probe.metrics) if probe.metrics is not None else None,
            },
            "live_probe_failure_streak": self.live_probe_failure_streak,
            "system_degraded": self.system_degraded,
            "kill_switch_engaged": self.kill_switch_engaged,
        }


@dataclass(frozen=True, slots=True)
class ExecutionAuthorityDecision:
    """The single result of the unified pipeline."""

    final_level: AxisLevel
    quorum: int
    original_level: AxisLevel
    original_quorum: int
    resolved_ceiling: ResolvedCeiling
    table_verdict: RiskTableVerdict
    feature_vector: FeatureVector
    catalog_version: str
    ceiling_inputs: CeilingInputs
    development_authority: DevelopmentAuthorityDecision | None = None

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
        """Return the replay-complete audit projection of this decision.

        ``feature_vector`` and ``catalog_version`` are serialized so a later
        replay can re-evaluate the recorded signals against the exact
        risk-classification revision that classified the action, instead of
        against whatever the catalog says today (risk-classification.md
        \N{SECTION SIGN} Audit). ``ceiling_inputs`` carries the remaining
        six-axis inputs - role, graph count, live-probe reading, and the two
        fail-safe flags - so the replay never re-queries a probe or re-reads
        control-plane health to reproduce the ceiling.
        """
        return {
            "decision": self.decision,
            "quorum": self.quorum,
            "original_decision": _LEVEL_TO_DECISION[self.original_level],
            "original_quorum": self.original_quorum,
            "effective_quorum": self.quorum,
            "matched_rule_id": self.table_verdict.rule_id,
            "catalog_version": self.catalog_version,
            "feature_vector": self.feature_vector.as_lookup(),
            "ceiling_inputs": self.ceiling_inputs.as_audit_dict(),
            "resolved_ceiling": self.resolved_ceiling.as_audit_dict(),
            **(
                {"development_authority": development_authority_audit(self.development_authority)}
                if self.development_authority is not None
                else {}
            ),
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
    live_probe_observation: LiveProbeObservation | None = None,
    live_probe_failure_streak: int = 0,
    system_degraded: bool = False,
    kill_switch_engaged: bool = False,
    development_profile: FullAuthorityDevelopmentProfile | Mapping[str, Any] | None = None,
    development_confirmation: DevelopmentActionConfirmation | Mapping[str, Any] | None = None,
    development_binding_source: DevelopmentAuthorityBindingSource | None = None,
    development_binding_request: DevelopmentAuthorityBindingRequest | None = None,
    evaluated_at: datetime | None = None,
) -> ExecutionAuthorityDecision:
    """Run the full pipeline and return one combined decision.

    ``environment`` is the normalized risk-table word (``"prod"`` /
    ``"non-prod"``); it is mapped to the ceiling's ``prod`` / ``non_prod``
    internally so both axes see a single environment classification.

    ``system_degraded`` (default ``False``) is the fail-toward-safety input:
    when a critical-dependency circuit breaker is open the control plane is
    DEGRADED and autonomy is capped to shadow (a failing dependency MUST NOT
    drive an enforce-mode mutation - csp-neutrality.md 4). It is an explicit
    input so a replay reproduces the decision exactly.

    ``kill_switch_engaged`` (default ``False``) is the operator emergency stop:
    when engaged, autonomy is capped to shadow so all auto-execution halts
    (security-and-identity.md). Like ``system_degraded`` it is an explicit
    input, so a replay reproduces the decision.

    ``live_probe_observation`` is the already-measured Axis-E reading and
    ``live_probe_failure_streak`` the count of consecutive blind attempts for
    the ActionType's ``live_probe_ref``. Both are explicit inputs so replay
    re-derives the axis without re-querying the probe (execution-model.md 4.2).
    When the ActionType declares a probe but no reading is supplied, the axis
    lowers to HIL rather than treating the missing signal as consent.
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
    probe_axis = resolve_live_probe_axis(
        action_type,
        observation=live_probe_observation,
        failure_streak=live_probe_failure_streak,
    )
    ceiling = resolve_ceiling(
        tier=tier,
        action_type=action_type,
        risk_table=verdict,
        principal_role=principal_role,
        env=_ceiling_env(environment),
        graph_affected=graph_affected,
        live_probe=probe_axis.result,
        live_probe_reason=probe_axis.reason,
        system_degraded=system_degraded,
        kill_switch_engaged=kill_switch_engaged,
    )
    final_level = ceiling.final_level
    effective_quorum = ceiling.final_quorum
    development_decision: DevelopmentAuthorityDecision | None = None
    if development_profile is not None:
        now = evaluated_at or datetime.now(tz=UTC)
        try:
            verification = (
                resolve_development_binding(
                    development_binding_source,
                    development_binding_request,
                    now=now,
                )
                if development_binding_request is not None
                else None
            )
        except ValueError:
            verification = None
        if verification is None:
            development_decision = DevelopmentAuthorityDecision(
                False,
                "binding_source_rejected",
            )
        elif (
            verification.binding.action_type != action_type.name
            or verification.binding.action_type_version != action_type.version
            or verification.binding.action_type_digest
            != "sha256:" + action_type_digest(action_type)
        ):
            development_decision = DevelopmentAuthorityDecision(
                False,
                "current_action_type_mismatch",
            )
        else:
            development_decision = evaluate_development_authority(
                development_profile,
                development_confirmation,
                verification,
                now=now,
                original_quorum=ceiling.final_quorum,
            )
        unsafe_evidence = (
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
        if not development_decision.eligible or unsafe_evidence:
            final_level = AxisLevel.DENY
            if unsafe_evidence:
                development_decision = DevelopmentAuthorityDecision(
                    eligible=False,
                    reason_code="safety_or_evidence_prerequisite_failed",
                )
        elif ceiling.final_level in {
            AxisLevel.ENFORCE_AUTO,
            AxisLevel.ENFORCE_HIL,
        } or _category_only_deny(ceiling, verdict):
            final_level = AxisLevel.ENFORCE_HIL
            effective_quorum = 1
    return ExecutionAuthorityDecision(
        final_level=final_level,
        quorum=effective_quorum,
        original_level=ceiling.final_level,
        original_quorum=ceiling.final_quorum,
        resolved_ceiling=ceiling,
        table_verdict=verdict,
        feature_vector=feature,
        catalog_version=table.version,
        ceiling_inputs=CeilingInputs(
            principal_role=None if principal_role is None else str(principal_role),
            graph_affected=graph_affected,
            live_probe=live_probe_observation,
            live_probe_failure_streak=live_probe_failure_streak,
            system_degraded=system_degraded,
            kill_switch_engaged=kill_switch_engaged,
        ),
        development_authority=development_decision,
    )


def _category_only_deny(
    ceiling: ResolvedCeiling,
    verdict: RiskTableVerdict,
) -> bool:
    """Return whether subscription impact category is the only deny source."""

    if verdict.rule_id != "deny-subscription-blast":
        return False
    denying_axes = {axis.name for axis in ceiling.axes if axis.level is AxisLevel.DENY}
    category_axes = {"risk_table", "static_blast"}
    return (
        bool(denying_axes)
        and denying_axes <= category_axes
        and all(
            axis.name in category_axes or axis.level >= AxisLevel.ENFORCE_HIL
            for axis in ceiling.axes
        )
    )


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


__all__ = ["CeilingInputs", "ExecutionAuthorityDecision", "evaluate_execution_authority"]
