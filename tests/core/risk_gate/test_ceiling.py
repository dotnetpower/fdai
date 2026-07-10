"""Six-axis execution-authority ceiling (execution-model.md 2).

Property tests assert the two structural guarantees:

- ``final_level == min(axis levels)`` over the full cartesian product of
  tier x table x blast x probe x role x env (execution-model.md 2.7).
- No axis ever raises the result above another (the never-raise rule).

Plus hand-picked corner cases for each axis's terminal behaviour.
"""

from __future__ import annotations

from itertools import product

from fdai.core.risk_gate.ceiling import (
    AxisLevel,
    resolve_ceiling,
)
from fdai.core.risk_gate.risk_table import RiskLevel, RiskTableVerdict
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingByTier,
    CeilingRole,
    EnvScope,
    ExecutionPath,
    OntologyActionType,
    Operation,
    ProdDowngrade,
    PromotionGate,
    RollbackKind,
    Tier,
    TierCeiling,
)


def RiskTableResult(  # noqa: N802 - test shim standing in for the unified verdict type
    *, level: str, quorum: int = 1, matched_rule_id: str = "test"
) -> RiskTableVerdict:
    return RiskTableVerdict(
        decision=RiskLevel(level), rule_id=matched_rule_id, quorum=quorum, reason="test"
    )


def _at(
    *,
    blast: ActionBlastRadius | None = None,
    ceiling: CeilingByTier | None = None,
    prod_downgrade: ProdDowngrade | None = None,
    execution_path: ExecutionPath | None = None,
    env_scope: EnvScope = EnvScope.ANY,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.example",
        version="1.0.0",
        operation=Operation.RESTART,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=blast,
        ceiling_by_tier=ceiling,
        prod_downgrade=prod_downgrade,
        execution_path=execution_path,
        env_scope=env_scope,
    )


def test_final_level_is_min_over_all_axes_and_never_raises() -> None:
    tiers = [Tier.T0, Tier.T1, Tier.T2]
    tables: list[str] = ["auto", "hil", "deny"]
    buckets = [
        None,
        BlastRadiusScope.RESOURCE,
        BlastRadiusScope.RESOURCE_GROUP,
        BlastRadiusScope.SUBSCRIPTION,
    ]
    probes: list[str | None] = [None, "quiet", "active", "overloaded"]
    roles = [None, CeilingRole.READER, CeilingRole.OWNER, "breakglass"]
    envs: list[str] = ["prod", "non_prod"]
    ceiling = CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.APPROVER),
        t1=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
        t2=TierCeiling(max_autonomy=Autonomy.SHADOW_ONLY, min_role=CeilingRole.APPROVER),
    )
    for tier, table, bucket, probe, role, env in product(
        tiers, tables, buckets, probes, roles, envs
    ):
        blast = (
            None
            if bucket is None
            else ActionBlastRadius(
                computation=BlastRadiusComputation.STATIC_ENUM, static_bucket=bucket
            )
        )
        rc = resolve_ceiling(
            tier=tier,
            action_type=_at(blast=blast, ceiling=ceiling),
            risk_table=RiskTableResult(level=table),
            principal_role=role,  # type: ignore[arg-type]
            env=env,  # type: ignore[arg-type]
            live_probe=probe,  # type: ignore[arg-type]
        )
        expected = min(a.level for a in rc.axes)
        assert rc.final_level == expected
        assert all(rc.final_level <= a.level for a in rc.axes)
        winner = next(a for a in rc.axes if a.name == rc.winning_axis)
        assert winner.level == rc.final_level


def test_subscription_blast_denies() -> None:
    blast = ActionBlastRadius(
        computation=BlastRadiusComputation.STATIC_ENUM, static_bucket=BlastRadiusScope.SUBSCRIPTION
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(blast=blast),
        risk_table=RiskTableResult(level="auto"),
        principal_role=CeilingRole.OWNER,
        env="non_prod",
    )
    assert rc.final_level == AxisLevel.DENY
    assert rc.winning_axis == "static_blast"


def test_missing_blast_radius_fails_closed_to_hil() -> None:
    """An ActionType with no declared blast_radius has an UNKNOWN impact
    surface, so the static_blast axis MUST cap at HIL, never fail open into
    auto. The catalog loader rejects a real entry that omits blast_radius;
    this guards hand-built ActionTypes (tests / fork adapters)."""

    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(blast=None),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="non_prod",
    )
    static = next(a for a in rc.axes if a.name == "static_blast")
    assert static.level == AxisLevel.ENFORCE_HIL
    assert rc.final_level <= AxisLevel.ENFORCE_HIL


def test_breakglass_is_never_auto() -> None:
    ceiling = CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.OWNER)
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(ceiling=ceiling),
        risk_table=RiskTableResult(level="auto"),
        principal_role="breakglass",
        env="non_prod",
    )
    assert rc.final_level <= AxisLevel.ENFORCE_HIL
    role_axis = next(a for a in rc.axes if a.name == "role")
    assert role_axis.level == AxisLevel.ENFORCE_HIL


def test_role_below_min_denies() -> None:
    ceiling = CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.OWNER)
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(ceiling=ceiling),
        risk_table=RiskTableResult(level="auto"),
        principal_role=CeilingRole.READER,
        env="non_prod",
    )
    assert rc.final_level == AxisLevel.DENY


def test_prod_downgrade_shadow_caps() -> None:
    pd = ProdDowngrade(mode=Autonomy.SHADOW_ONLY, detection_ref="env_detectors/tag")
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(prod_downgrade=pd),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="prod",
    )
    assert rc.final_level <= AxisLevel.SHADOW_ONLY


def test_t2_is_hard_capped_to_shadow_even_with_aggressive_ceiling() -> None:
    ceiling = CeilingByTier(
        t2=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.READER)
    )
    rc = resolve_ceiling(
        tier=Tier.T2,
        action_type=_at(ceiling=ceiling),
        risk_table=RiskTableResult(level="auto"),
        principal_role=CeilingRole.OWNER,
        env="non_prod",
    )
    assert rc.final_level <= AxisLevel.SHADOW_ONLY


def test_table_deny_denies() -> None:
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(),
        risk_table=RiskTableResult(level="deny"),
        principal_role=None,
        env="non_prod",
    )
    assert rc.final_level == AxisLevel.DENY
    assert rc.winning_axis == "risk_table"


def test_all_clear_yields_enforce_auto() -> None:
    blast = ActionBlastRadius(
        computation=BlastRadiusComputation.STATIC_ENUM, static_bucket=BlastRadiusScope.RESOURCE
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(blast=blast),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="non_prod",
        live_probe="quiet",
    )
    assert rc.final_level == AxisLevel.ENFORCE_AUTO


def test_live_overloaded_caps_shadow() -> None:
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="non_prod",
        live_probe="overloaded",
    )
    assert rc.final_level <= AxisLevel.SHADOW_ONLY


def test_graph_derived_over_cap_caps_hil() -> None:
    blast = ActionBlastRadius(
        computation=BlastRadiusComputation.GRAPH_DERIVED, max_affected_resources=5
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(blast=blast),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="non_prod",
        graph_affected=9,
    )
    assert rc.final_level <= AxisLevel.ENFORCE_HIL


def test_quorum_flows_from_table() -> None:
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(),
        risk_table=RiskTableResult(level="hil", quorum=2, matched_rule_id="irreversible"),
        principal_role=None,
        env="non_prod",
    )
    assert rc.final_quorum == 2


def test_graph_derived_within_cap_is_neutral() -> None:
    blast = ActionBlastRadius(
        computation=BlastRadiusComputation.GRAPH_DERIVED, max_affected_resources=5
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(blast=blast),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="non_prod",
        graph_affected=3,
    )
    static = next(a for a in rc.axes if a.name == "static_blast")
    assert static.level == AxisLevel.ENFORCE_AUTO
    assert rc.final_level == AxisLevel.ENFORCE_AUTO


def test_prod_without_downgrade_but_non_prod_scope_is_neutral() -> None:
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(env_scope=EnvScope.NON_PROD),
        risk_table=RiskTableResult(level="auto"),
        principal_role=None,
        env="prod",
    )
    env_axis = next(a for a in rc.axes if a.name == "env")
    assert env_axis.level == AxisLevel.ENFORCE_AUTO


def test_audit_dict_shape() -> None:
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(execution_path=ExecutionPath.DIRECT_API),
        risk_table=RiskTableResult(level="hil"),
        principal_role=None,
        env="non_prod",
    )
    d = rc.as_audit_dict()
    assert d["tier"] == "t0"
    assert set(d["axes"]) == {
        "risk_table",
        "tier",
        "ceiling",
        "static_blast",
        "live_blast",
        "role",
        "env",
    }
    assert d["final_path"] == "direct_api"
    assert d["final_level"] in {"deny", "shadow_only", "enforce_hil", "enforce_auto"}


# ---------------------------------------------------------------------------
# tool_call path integration (execution-model.md 5.6)
# ---------------------------------------------------------------------------


def test_tool_call_path_is_preserved_in_resolved_ceiling() -> None:
    """A tool_call ActionType's resolved ceiling carries final_path=tool_call
    and serialises the value the resolved-ceiling schema now accepts."""
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(execution_path=ExecutionPath.TOOL_CALL),
        risk_table=RiskTableResult(level="hil"),
        principal_role=None,
        env="non_prod",
    )
    assert rc.final_path is ExecutionPath.TOOL_CALL
    assert rc.as_audit_dict()["final_path"] == "tool_call"


def test_tool_style_auto_table_is_capped_at_hil_by_ceiling() -> None:
    """The safety claim behind tool.generate-pdf: a reversible,
    resource-scoped, control-plane tool matches the risk-table
    auto-low-risk row, but a t0 ENFORCE_HIL ceiling caps autonomy at HIL
    so it never auto-executes just because the table said auto."""
    ceiling = CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.APPROVER),
    )
    blast = ActionBlastRadius(
        computation=BlastRadiusComputation.STATIC_ENUM, static_bucket=BlastRadiusScope.RESOURCE
    )
    rc = resolve_ceiling(
        tier=Tier.T0,
        action_type=_at(
            execution_path=ExecutionPath.TOOL_CALL, blast=blast, ceiling=ceiling
        ),
        risk_table=RiskTableResult(level="auto"),
        principal_role=CeilingRole.OWNER,
        env="non_prod",
    )
    assert rc.final_level == AxisLevel.ENFORCE_HIL
    assert rc.winning_axis == "ceiling"
