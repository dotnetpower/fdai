"""Six-axis execution-authority ceiling (execution-model.md 2).

Pure, synchronous ceiling calculation combined with the authoritative
risk-classification table result via ``min()``. **Nothing here raises
autonomy**: every axis returns a level and the final decision is the least
autonomous one (the ``min``). See execution-model.md 2 and
action-ontology.md 2 for the field definitions.

This module is deliberately kept out of the existing :mod:`gate` module so
the shipped :class:`~fdai.core.risk_gate.gate.RiskGate` behaviour is
unchanged; the unified RiskGate wires this in during the Week-1 rollout
(execution-model.md 9). It performs no I/O - the live-probe result and the
risk-classification table verdict are passed in, already computed, so a
replay is deterministic (execution-model.md 3, 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Literal

from fdai.core.risk_gate.risk_table import RiskLevel, RiskTableVerdict
from fdai.shared.contracts.models import (
    Autonomy,
    BlastRadiusScope,
    CeilingRole,
    ExecutionPath,
    OntologyActionType,
    Tier,
)


class AxisLevel(IntEnum):
    """Ordered autonomy levels. Higher value = more autonomous.

    ``min()`` over the axes yields the LEAST autonomous outcome, which is
    exactly the never-raising combination rule in execution-model.md 2.7.
    """

    DENY = 0
    SHADOW_ONLY = 1
    ENFORCE_HIL = 2
    ENFORCE_AUTO = 3


ProbeResult = Literal["quiet", "active", "overloaded"]
PrincipalRole = CeilingRole | Literal["breakglass"] | None
Env = Literal["prod", "non_prod"]


_AUTONOMY_TO_AXIS: dict[Autonomy, AxisLevel] = {
    Autonomy.SHADOW_ONLY: AxisLevel.SHADOW_ONLY,
    Autonomy.ENFORCE_HIL: AxisLevel.ENFORCE_HIL,
    Autonomy.ENFORCE_AUTO: AxisLevel.ENFORCE_AUTO,
}

_TABLE_TO_AXIS: dict[RiskLevel, AxisLevel] = {
    RiskLevel.AUTO: AxisLevel.ENFORCE_AUTO,
    RiskLevel.HIL: AxisLevel.ENFORCE_HIL,
    RiskLevel.DENY: AxisLevel.DENY,
}

_ROLE_RANK: dict[CeilingRole, int] = {
    CeilingRole.READER: 0,
    CeilingRole.CONTRIBUTOR: 1,
    CeilingRole.APPROVER: 2,
    CeilingRole.OWNER: 3,
}

# Axis C conservative upstream default when the ActionType declares no
# ``ceiling_by_tier`` for the tier: T0 auto, T1 HIL, T2 shadow-only.
_TIER_DEFAULT_CEILING: dict[Tier, AxisLevel] = {
    Tier.T0: AxisLevel.ENFORCE_AUTO,
    Tier.T1: AxisLevel.ENFORCE_HIL,
    Tier.T2: AxisLevel.SHADOW_ONLY,
}

# Axis B hard cap by tier. Only T2 is hard-capped to shadow-only by the
# tier itself; T0/T1 are opened here so a fork MAY raise T1 via
# ``ceiling_by_tier`` (Axis C). T2 stays shadow-only unless a Rego overlay
# (a separate layer, not this pure module) lifts it - see execution-model.md 2.1.
_TIER_HARD_CAP: dict[Tier, AxisLevel] = {
    Tier.T0: AxisLevel.ENFORCE_AUTO,
    Tier.T1: AxisLevel.ENFORCE_AUTO,
    Tier.T2: AxisLevel.SHADOW_ONLY,
}


@dataclass(frozen=True, slots=True)
class AxisContribution:
    name: str
    level: AxisLevel
    reason: str


@dataclass(frozen=True, slots=True)
class ResolvedCeiling:
    """Full 6-axis + table breakdown (execution-model.md 8)."""

    tier: Tier
    action_type_name: str
    axes: tuple[AxisContribution, ...]
    winning_axis: str
    final_level: AxisLevel
    final_quorum: int
    final_path: ExecutionPath | None

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "action_type_id": self.action_type_name,
            "axes": {
                a.name: {"level": a.level.name.lower(), "reason": a.reason} for a in self.axes
            },
            "winning_axis": self.winning_axis,
            "final_level": self.final_level.name.lower(),
            "final_quorum": self.final_quorum,
            "final_path": self.final_path.value if self.final_path is not None else None,
        }


def _tier_ceiling(tier: Tier, at: OntologyActionType) -> Autonomy | None:
    if at.ceiling_by_tier is None:
        return None
    tc = {
        Tier.T0: at.ceiling_by_tier.t0,
        Tier.T1: at.ceiling_by_tier.t1,
        Tier.T2: at.ceiling_by_tier.t2,
    }[tier]
    return tc.max_autonomy if tc is not None else None


def _tier_min_role(tier: Tier, at: OntologyActionType) -> CeilingRole | None:
    if at.ceiling_by_tier is None:
        return None
    tc = {
        Tier.T0: at.ceiling_by_tier.t0,
        Tier.T1: at.ceiling_by_tier.t1,
        Tier.T2: at.ceiling_by_tier.t2,
    }[tier]
    return tc.min_role if tc is not None else None


def _axis_a_table(v: RiskTableVerdict) -> AxisContribution:
    return AxisContribution(
        name="risk_table",
        level=_TABLE_TO_AXIS[v.decision],
        reason=f"risk-classification matched_rule={v.rule_id}",
    )


def _axis_b_tier(tier: Tier) -> AxisContribution:
    return AxisContribution(name="tier", level=_TIER_HARD_CAP[tier], reason=f"tier={tier.value}")


def _axis_c_ceiling(tier: Tier, at: OntologyActionType) -> AxisContribution:
    declared = _tier_ceiling(tier, at)
    if declared is not None:
        return AxisContribution(
            "ceiling", _AUTONOMY_TO_AXIS[declared], f"ceiling_by_tier.{tier.value}.max_autonomy"
        )
    return AxisContribution("ceiling", _TIER_DEFAULT_CEILING[tier], f"tier default ({tier.value})")


def _axis_d_static_blast(at: OntologyActionType, graph_affected: int | None) -> AxisContribution:
    br = at.blast_radius
    if br is None:
        # Fail-closed: an ActionType with no declared blast radius has an
        # UNKNOWN impact surface, so this axis caps at HIL rather than
        # failing open into auto. The catalog loader
        # (rule_catalog/schema/action_type.py) rejects a real catalog
        # entry that omits blast_radius, so in production this branch is
        # never reached; it only guards a hand-built ActionType (tests /
        # fork adapters) so an unknown blast can never fail open into
        # auto (action-ontology.md 2).
        return AxisContribution(
            "static_blast",
            AxisLevel.ENFORCE_HIL,
            "no blast_radius declared (unknown impact -> HIL)",
        )
    if br.computation.value == "graph_derived":
        cap = br.max_affected_resources
        if graph_affected is None or cap is None:
            # Fail-closed: a graph_derived blast whose runtime affected-
            # count was NOT measured (the caller did not walk the ontology
            # graph via blast_radius_simulator), or whose cap is
            # undeclared, has an UNKNOWN impact surface - cap at HIL
            # rather than fail open into auto. This mirrors the RiskGate
            # blast-radius count=None guard: an unknown blast can never be
            # auto. (The control loop does not yet supply graph_affected,
            # so graph_derived actions correctly cap at HIL until the
            # simulator is wired.)
            return AxisContribution(
                "static_blast",
                AxisLevel.ENFORCE_HIL,
                "graph_derived unknown affected-count or cap -> HIL",
            )
        if graph_affected > cap:
            return AxisContribution(
                "static_blast",
                AxisLevel.ENFORCE_HIL,
                f"graph_derived affected={graph_affected}>max={cap}",
            )
        return AxisContribution("static_blast", AxisLevel.ENFORCE_AUTO, "graph_derived within cap")
    bucket = br.static_bucket
    if bucket is BlastRadiusScope.SUBSCRIPTION:
        return AxisContribution("static_blast", AxisLevel.DENY, "static_bucket=subscription")
    if bucket is BlastRadiusScope.RESOURCE_GROUP:
        return AxisContribution(
            "static_blast", AxisLevel.ENFORCE_HIL, "static_bucket=resource_group"
        )
    return AxisContribution("static_blast", AxisLevel.ENFORCE_AUTO, "static_bucket=resource")


def _axis_e_live_blast(probe: ProbeResult | None) -> AxisContribution:
    if probe is None:
        return AxisContribution("live_blast", AxisLevel.ENFORCE_AUTO, "no live probe (no opinion)")
    mapping: dict[str, AxisLevel] = {
        "quiet": AxisLevel.ENFORCE_AUTO,
        "active": AxisLevel.ENFORCE_HIL,
        "overloaded": AxisLevel.SHADOW_ONLY,
    }
    return AxisContribution("live_blast", mapping[probe], f"probe={probe}")


def _axis_f_role(
    tier: Tier, at: OntologyActionType, principal_role: PrincipalRole
) -> AxisContribution:
    min_role = _tier_min_role(tier, at)
    # BreakGlass is off-ladder: it makes the caller eligible to approve a
    # HIL item, but never returns auto (user-rbac-and-identity.md 2). It is
    # the only non-CeilingRole, non-None principal value.
    if principal_role is not None and not isinstance(principal_role, CeilingRole):
        return AxisContribution("role", AxisLevel.ENFORCE_HIL, "breakglass eligible (never auto)")
    if min_role is None:
        return AxisContribution("role", AxisLevel.ENFORCE_AUTO, "no min_role (unrestricted)")
    if principal_role is None:
        return AxisContribution("role", AxisLevel.DENY, f"no principal < min_role={min_role.value}")
    if _ROLE_RANK[principal_role] >= _ROLE_RANK[min_role]:
        return AxisContribution(
            "role",
            AxisLevel.ENFORCE_AUTO,
            f"principal={principal_role.value}>=min_role={min_role.value}",
        )
    return AxisContribution(
        "role", AxisLevel.DENY, f"principal={principal_role.value}<min_role={min_role.value}"
    )


def _axis_g_env(at: OntologyActionType, env: Env) -> AxisContribution:
    if env != "prod":
        return AxisContribution("env", AxisLevel.ENFORCE_AUTO, "not-prod")
    pd = at.prod_downgrade
    if pd is not None:
        return AxisContribution(
            "env", _AUTONOMY_TO_AXIS[pd.mode], f"prod_downgrade.mode={pd.mode.value}"
        )
    if at.env_scope.value == "non_prod":
        return AxisContribution(
            "env",
            AxisLevel.ENFORCE_AUTO,
            "env_scope=non_prod (dev-only; prod handled by risk_table)",
        )
    # any/prod without prod_downgrade: the risk-classification env signal
    # (Axis A) is authoritative for prod here, so this axis stays neutral.
    return AxisContribution(
        "env", AxisLevel.ENFORCE_AUTO, "prod without prod_downgrade (deferred to risk_table env)"
    )


def _axis_h_system_health() -> AxisContribution:
    """System-level fail-toward-safety axis (csp-neutrality.md 4).

    Emitted only when the control plane is DEGRADED - one or more critical
    dependencies (audit store, event bus, substrate) have a tripped circuit
    breaker. A failing dependency MUST NOT drive an enforce-mode mutation,
    so this axis caps autonomy to shadow; the ``min()`` combine then floors
    the whole decision at shadow (or lower, if another axis denies). See
    :class:`~fdai.shared.resilience.degradation.DegradationController`.
    """
    return AxisContribution(
        "system_health",
        AxisLevel.SHADOW_ONLY,
        "degraded: critical dependency circuit open (autonomy capped to shadow)",
    )


def _axis_kill_switch() -> AxisContribution:
    """Operator-triggered global emergency-halt axis (security-and-identity.md).

    Emitted only when the global kill-switch is ENGAGED - a deliberate operator
    action (RBAC ``TRIGGER_KILL_SWITCH``) that halts all auto-execution
    immediately. Caps autonomy to shadow so no action mutates while the halt is
    active; the ``min()`` combine floors the whole decision at shadow (a human
    path stays open via HIL). See
    :class:`~fdai.shared.resilience.kill_switch.KillSwitch`.
    """
    return AxisContribution(
        "kill_switch",
        AxisLevel.SHADOW_ONLY,
        "kill_switch engaged: all auto-execution halted (operator emergency stop)",
    )


def resolve_ceiling(
    *,
    tier: Tier,
    action_type: OntologyActionType,
    risk_table: RiskTableVerdict,
    principal_role: PrincipalRole,
    env: Env,
    graph_affected: int | None = None,
    live_probe: ProbeResult | None = None,
    system_degraded: bool = False,
    kill_switch_engaged: bool = False,
) -> ResolvedCeiling:
    """Combine the risk-classification table with the six ceiling axes.

    Returns the least-autonomous level (``min`` over every axis) plus a
    full per-axis breakdown for the audit entry. The final quorum comes
    from the table (Axis A). No axis can raise the result above another.

    ``system_degraded`` (default ``False``) adds a seventh fail-safe axis
    (``system_health``) capped to shadow when a critical dependency circuit
    is open, so a DEGRADED control plane can never emit an enforce-mode
    decision (csp-neutrality.md 4). The axis is appended ONLY when degraded,
    so the healthy path is byte-identical to the six-axis result.

    ``kill_switch_engaged`` (default ``False``) adds the operator-triggered
    ``kill_switch`` emergency-halt axis, also capped to shadow
    (security-and-identity.md). Both fail-safe axes are appended only when
    active, so the normal path stays byte-identical to the six-axis result.
    """
    axes: tuple[AxisContribution, ...] = (
        _axis_a_table(risk_table),
        _axis_b_tier(tier),
        _axis_c_ceiling(tier, action_type),
        _axis_d_static_blast(action_type, graph_affected),
        _axis_e_live_blast(live_probe),
        _axis_f_role(tier, action_type, principal_role),
        _axis_g_env(action_type, env),
    )
    if system_degraded:
        axes = (*axes, _axis_h_system_health())
    if kill_switch_engaged:
        axes = (*axes, _axis_kill_switch())
    winning = min(axes, key=lambda a: a.level)
    return ResolvedCeiling(
        tier=tier,
        action_type_name=action_type.name,
        axes=axes,
        winning_axis=winning.name,
        final_level=winning.level,
        final_quorum=risk_table.quorum,
        final_path=action_type.execution_path,
    )


__all__ = [
    "AxisContribution",
    "AxisLevel",
    "Env",
    "PrincipalRole",
    "ProbeResult",
    "ResolvedCeiling",
    "resolve_ceiling",
]
